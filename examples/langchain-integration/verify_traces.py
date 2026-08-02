"""Verify that the LangChain example wrote events to the SQLite store."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "packages", "python-sdk"))

from agent_devtools.store import default_db_path

db = default_db_path()
print(f"DB: {db}")
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

runs = conn.execute("SELECT id, agent_name, status FROM runs ORDER BY started_at DESC").fetchall()
print("\nRUNS:")
for r in runs:
    print(f"  {r['id']} ({r['agent_name']}, {r['status']})")

print("\nEVENTS:")
for r in conn.execute("SELECT run_id, type, payload FROM events ORDER BY run_id, seq"):
    payload = json.loads(r["payload"])
    print(f"  {r['run_id']}: {r['type']} -> {json.dumps(payload)[:120]}")