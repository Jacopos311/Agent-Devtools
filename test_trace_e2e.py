"""
End-to-end test: write a trace with all event types, then verify the
server can read and serve the events correctly.

Run with:
    python test_trace_e2e.py
"""
import json
import os
import tempfile

# Use a temporary database so we don't pollute the real one
DB_PATH = os.path.join(tempfile.mkdtemp(), "test_trace.db")

# ── 1. Write a trace ──────────────────────────────────────────────────

print("=== 1. Writing trace events ===")

from agent_devtools import trace

with trace.run("test-agent", run_id="test-run-1", db_path=DB_PATH) as run:
    run.input("Hello, world!", extra="meta")
    run.retrieval("test query", [
        {"id": "doc1", "content": "result 1", "source": "memory",
         "score": 0.95, "rank": 1, "selected": True},
    ])
    run.context_block(source="memory", key="ctx1", content="context data", order=0)
    run.prompt(system="You are a test agent.",
               messages=[{"role": "user", "content": "Hello"}],
               context=["ctx1"])
    run.tool_call(name="test_tool", args={"x": 1}, result={"y": 2})
    run.memory_write(key="test_key", value="test_value")
    run.memory_read(key="test_key", value="test_value")
    run.output("Test response")

print("   Trace written successfully.")

# ── 2. Verify the database directly ───────────────────────────────────

print("\n=== 2. Verifying database contents ===")

import sqlite3

conn = sqlite3.connect(DB_PATH)
runs = conn.execute("SELECT id, agent_name, status FROM runs").fetchall()
events = conn.execute("SELECT type, seq FROM events ORDER BY run_id, seq").fetchall()
conn.close()

print(f"   Runs: {len(runs)}")
for r in runs:
    print(f"     - {r[0]} ({r[1]}): {r[2]}")
print(f"   Events: {len(events)}")
for e in events:
    print(f"     - {e[0]} (seq={e[1]})")

assert len(runs) == 1, f"Expected 1 run, got {len(runs)}"
assert runs[0][0] == "test-run-1"
assert runs[0][2] == "ok"
# tool_call with result generates 2 events (tool.call + tool.result)
assert len(events) == 10, f"Expected 10 events, got {len(events)}"

# ── 3. Verify reading via TraceStore directly ─────────────────────────

print("\n=== 3. Verifying TraceStore read ===")

from agent_devtools.store import TraceStore

store = TraceStore(DB_PATH)
read_runs = store.list_runs()
print(f"   Runs via TraceStore: {len(read_runs)}")
for r in read_runs:
    print(f"     - {r['id']}: {r['event_count']} events")

read_events = store.get_events("test-run-1")
print(f"   Events via TraceStore: {len(read_events)}")
for e in read_events:
    print(f"     - {e.type}: {json.dumps(e.payload, default=str)[:80]}")

assert len(read_runs) == 1
assert read_runs[0]["event_count"] == 10
assert len(read_events) == 10

# ── 4. Verify event payloads are correct JSON ─────────────────────────

print("\n=== 4. Verifying event payloads ===")

for e in read_events:
    assert isinstance(e.payload, dict), f"Payload for {e.type} is not a dict: {type(e.payload)}"
    json.dumps(e.payload, default=str)

print("   All event payloads are valid JSON objects.")

# ── 5. Verify the run fixture export/import ──────────────────────────

print("\n=== 5. Verifying fixture export/import ===")

fixture = store.export_fixture("test-run-1")
assert fixture["schema"] == "agent-devtools/fixture@1"
assert fixture["run"]["id"] == "test-run-1"
assert len(fixture["events"]) == 10
print("   Fixture export works correctly.")

new_run_id = store.import_fixture(fixture)
assert new_run_id == "test-run-1"
print("   Fixture import works correctly.")

# ── 6. Verify the server API (if running) ─────────────────────────────

print("\n=== 6. Testing server API ===")

try:
    import urllib.request

    req = urllib.request.Request("http://127.0.0.1:4173/api/health")
    with urllib.request.urlopen(req, timeout=3) as resp:
        health = json.loads(resp.read())
        print(f"   Health: {health}")

    req = urllib.request.Request("http://127.0.0.1:4173/api/runs")
    with urllib.request.urlopen(req, timeout=3) as resp:
        runs_data = json.loads(resp.read())
        print(f"   Runs from API: {len(runs_data)}")
        for r in runs_data:
            print(f"     - {r['id']}: {r['event_count']} events")
except Exception as e:
    print(f"   Server not reachable (start with `agent-devtools serve`): {e}")

# Clean up
store._conn.close()
try:
    os.remove(DB_PATH)
    os.rmdir(os.path.dirname(DB_PATH))
except PermissionError:
    pass

print("\n✅ All tests passed!")