"""
Deterministic Replay verification: engine statuses (completed / diverged /
failed), divergence evidence, ReplayReport persistence in the store, and the
three HTTP endpoints.

Run with:
    python3 test_replay.py
"""
import json
import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SDK = os.path.join(_REPO_ROOT, "packages", "python-sdk")
if _SDK not in sys.path:
    sys.path.insert(0, _SDK)

from agent_devtools.store import TraceStore
from agent_devtools.replay import ReplayEngine

DB = os.path.join(tempfile.mkdtemp(), "replay.db")
store = TraceStore(DB)


def mk_run(run_id, status="ok", events=()):
    store.create_run(run_id, "test-agent", {"mode": "test"})
    for et, payload in events:
        store.log_event(run_id, et, payload)
    store.finish_run(run_id, status)


# ---------------------------------------------------------------------------
# 1. completed -- consistent log replays without divergence
# ---------------------------------------------------------------------------
print("=== 1. completed replay ===")
mk_run("r-completed", events=[
    ("user.input", {"message": "What does Pro cost?"}),
    ("memory.write", {"key": "plan_price", "value": "$29/mo", "source": "pricing_doc"}),
    ("memory.read", {"key": "plan_price", "value": "$29/mo"}),
    ("retrieval.result", {"results": [
        {"id": "doc", "content": "Pro is $29/mo", "source": "doc", "score": 0.9, "rank": 1, "selected": True},
        {"id": "mem", "content": "plan price $19/mo", "source": "memory", "score": 0.62, "rank": 2, "selected": False},
    ]}),
    ("tool.call", {"name": "lookup_price"}),
    ("tool.result", {"name": "lookup_price", "result": "$29/mo"}),
    ("assertion.passed", {"name": "price_matches_doc"}),
    ("model.response", {"response": "Pro costs $29/mo."}),
])
rep = ReplayEngine(store).replay("r-completed")
assert rep.status == "completed", rep.status
assert rep.assertions["passed"] == 1 and rep.assertions["failed"] == 0
assert rep.output == "Pro costs $29/mo."
assert rep.memory_final == {"plan_price": "$29/mo"}
print("[OK]", rep.status, "|", rep.summary)

# ---------------------------------------------------------------------------
# 2. diverged -- stale memory read (recording contradicts the replay chain)
# ---------------------------------------------------------------------------
print("\n=== 2. diverged: stale memory read ===")
mk_run("r-stale-mem", events=[
    ("memory.write", {"key": "plan_price", "value": "$29/mo"}),
    # The agent read $19/mo although the write chain above set $29/mo.
    ("memory.read", {"key": "plan_price", "value": "$19/mo", "source": "memory"}),
    ("model.response", {"response": "Pro costs $19/mo."}),
])
rep = ReplayEngine(store).replay("r-stale-mem")
assert rep.status == "diverged", rep.status
kinds = [ev["kind"] for ev in rep.evidence]
assert "memory.read.stale" in kinds
stale = next(ev for ev in rep.evidence if ev["kind"] == "memory.read.stale")
assert stale["severity"] == "divergence"
assert stale["expected"] == "$29/mo" and stale["actual"] == "$19/mo"
print("[OK]", rep.status, "|", stale["message"])

# ---------------------------------------------------------------------------
# 3. diverged -- memory.update on a different old_value
# ---------------------------------------------------------------------------
print("\n=== 3. diverged: memory.update old_value mismatch ===")
mk_run("r-update", events=[
    ("memory.write", {"key": "addr", "value": "Rome"}),
    ("memory.update", {"key": "addr", "old_value": "Milan", "new_value": "Paris"}),
])
rep = ReplayEngine(store).replay("r-update")
assert rep.status == "diverged", rep.status
assert any(ev["kind"] == "memory.update.old_value" for ev in rep.evidence)
print("[OK]", rep.status, "| memory.update.old_value evidence present")

# ---------------------------------------------------------------------------
# 4. diverged -- retrieval rank contradicts scores
# ---------------------------------------------------------------------------
print("\n=== 4. diverged: retrieval rank flip ===")
mk_run("r-rank", events=[
    ("retrieval.result", {"results": [
        {"id": "b", "score": 0.9, "rank": 1, "selected": True},  # score orders it #2
        {"id": "a", "score": 0.95, "rank": 2, "selected": False},
    ]}),
])
rep = ReplayEngine(store).replay("r-rank")
assert rep.status == "diverged", rep.status
kinds = [ev["kind"] for ev in rep.evidence]
assert "retrieval.rank" in kinds
print("[OK]", rep.status, "| retrieval.rank evidence present")

# ---------------------------------------------------------------------------
# 5. diverged -- selection contradicts scores
# ---------------------------------------------------------------------------
print("\n=== 5. diverged: selection not score-monotone ===")
mk_run("r-sel", events=[
    ("retrieval.result", {"results": [
        {"id": "low", "score": 0.4, "rank": 1, "selected": True},
        {"id": "high", "score": 0.9, "rank": 2, "selected": False},
    ]}),
])
rep = ReplayEngine(store).replay("r-sel")
assert rep.status == "diverged", rep.status
assert any(ev["kind"] == "retrieval.selection" for ev in rep.evidence)
print("[OK]", rep.status, "| retrieval.selection evidence present")
# ---------------------------------------------------------------------------
# 6. failed -- recorded assertion.failed
# ---------------------------------------------------------------------------
print("\n=== 6. failed replay: assertion.failed recorded ===")
mk_run("r-assert", status="error", events=[
    ("assertion.passed", {"name": "input_present"}),
    ("assertion.failed", {"name": "price_ok", "details": "quoted stale price"}),
])
rep = ReplayEngine(store).replay("r-assert")
assert rep.status == "failed", rep.status
assert rep.assertions == {"passed": 1, "failed": 1}
assert any(ev["kind"] == "assertion.failed" for ev in rep.evidence)
print("[OK]", rep.status, "|", rep.summary)

# ---------------------------------------------------------------------------
# 7. failed -- run status error without assertions
# ---------------------------------------------------------------------------
print("\n=== 7. failed replay: run ended with status 'error' ===")
mk_run("r-error", status="error", events=[("user.input", {"message": "hi"})])
rep = ReplayEngine(store).replay("r-error")
assert rep.status == "failed", rep.status
print("[OK]", rep.status, "|", rep.summary)

# ---------------------------------------------------------------------------
# 8. notes do not change the outcome
# ---------------------------------------------------------------------------
print("\n=== 8. external memory / dangling tool are notes, not divergence ===")
mk_run("r-notes", events=[
    ("memory.read", {"key": "external_key", "value": "from-db"}),
    ("tool.call", {"name": "unfinished_tool"}),
])
rep = ReplayEngine(store).replay("r-notes")
assert rep.status == "completed", rep.status
kinds = [ev["kind"] for ev in rep.evidence]
assert "memory.read.external" in kinds and "tool.dangling" in kinds
assert all(ev["severity"] == "note" for ev in rep.evidence)
print("[OK]", rep.status, "| notes:", sorted(kinds))
# ---------------------------------------------------------------------------
# 9. store persistence: save / list / get + cascade deletes
# ---------------------------------------------------------------------------
print("\n=== 9. replay persistence in the store ===")
report = ReplayEngine(store).replay("r-completed").to_dict()
rid = store.save_replay("r-completed", report)
listed = store.list_replays("r-completed")
assert len(listed) == 1 and listed[0]["id"] == rid and listed[0]["status"] == "completed"
fetched = store.get_replay("r-completed", rid)
assert fetched["run_id"] == "r-completed"
assert fetched["report"]["status"] == "completed"
assert fetched["report"]["events_replayed"] == 8
assert '"summary"' in json.dumps(fetched["report"])  # JSON round-trip
# Persisting a ReplayReport object directly also works.
rid2 = store.save_replay("r-completed", ReplayEngine(store).replay("r-completed"))
assert len(store.list_replays("r-completed")) == 2
# Cascade delete on delete_run.
store.delete_run("r-completed")
assert store.list_replays("r-completed") == []
print("[OK] save/list/get + cascade delete on delete_run")

# Persisting a ReplayReport without a replay_id assigns one, and reads are
# scoped to the run.
store.save_replay("r-scope", {"replay_id": "manual", "run_id": "r-scope",
                              "created_at": 1.0, "status": "completed",
                              "summary": "manual", "events_replayed": 0,
                              "steps": [], "evidence": [], "assertions": {},
                              "output": None, "memory_final": {}, "run_status": "ok"})
assert store.get_replay("r-scope", "manual") is not None
assert store.get_replay("other", "manual") is None  # wrong run -> not found
print("[OK] get_replay scoped by run_id")

# ---------------------------------------------------------------------------
# 10. HTTP endpoints
# ---------------------------------------------------------------------------
print("\n=== 10. server endpoints ===")
mk_run("r-http", events=[
    ("memory.write", {"key": "plan_price", "value": "$29/mo"}),
    ("memory.read", {"key": "plan_price", "value": "$19/mo"}),
    ("model.response", {"response": "Pro costs $19/mo."}),
])
os.environ["AGENT_DEVTOOLS_DB"] = DB
try:
    from fastapi.testclient import TestClient
    import importlib
    import agent_devtools.server.main as m
    importlib.reload(m)
    c = TestClient(m.app)

    # POST /api/runs/{run_id}/replay
    r = c.post("/api/runs/r-http/replay")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replay_id"] and body["report"]["status"] == "diverged"
    rid = body["replay_id"]
    print(f"[OK] POST /api/runs/r-http/replay -> {body['report']['status']} ({rid})")

    # GET /api/runs/{run_id}/replays
    r = c.get("/api/runs/r-http/replays")
    assert r.status_code == 200 and len(r.json()["replays"]) == 1
    print("[OK] GET /api/runs/r-http/replays ->", r.json()["replays"][0]["status"])

    # GET /api/runs/{run_id}/replay/{replay_id}/report
    r = c.get(f"/api/runs/r-http/replay/{rid}/report")
    assert r.status_code == 200
    rep_report = r.json()["replay"]["report"]
    assert rep_report["status"] == "diverged"
    assert any(ev["kind"] == "memory.read.stale" for ev in rep_report["evidence"])
    print("[OK] GET report -> diverged with memory.read.stale evidence")

    # 404 case
    assert c.post("/api/runs/does-not-exist/replay").status_code == 404
    print("[OK] POST replay for unknown run -> 404")
except ImportError:
    print("[SKIP] fastapi testclient unavailable")

print("\nALL REPLAY TESTS PASSED")
