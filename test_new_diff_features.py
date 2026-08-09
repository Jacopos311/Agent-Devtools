"""Verify new Behavior Diff capabilities: token diff, scored causes, multi-run.

Run:  python3 test_new_diff_features.py
"""
import os, sys, tempfile, json

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SDK = os.path.join(_REPO_ROOT, "packages", "python-sdk")
if _SDK not in sys.path:
    sys.path.insert(0, _SDK)

from agent_devtools import TraceStore, diff_runs, diff_runs_multi

DB = os.path.join(tempfile.mkdtemp(), "newdiff.db")
store = TraceStore(DB)


def mk_run(run_id, system, question, answer, extra=None):
    store.create_run(run_id, "agent")
    store.log_event(run_id, "user.input", {"message": question})
    store.log_event(run_id, "prompt.assembled",
                    {"system": system,
                     "messages": [{"role": "user", "content": question}]})
    store.log_event(run_id, "model.response", {"response": answer})
    store.finish_run(run_id, "ok")


# Memory-driven runs: stale value leaks into answer.
for rid, mem, ans in [("good", "$29/mo", "Pro costs $29/mo."),
                      ("bad1", "$19/mo", "Pro costs $19/mo."),
                      ("bad2", "$19/mo", "Pro costs $19/mo.")]:
    store.create_run(rid, "refund-agent")
    store.log_event(rid, "user.input", {"message": "Pro price?"})
    store.log_event(rid, "retrieval.query", {"query": "Pro price"})
    store.log_event(rid, "retrieval.result", {"query": "Pro price", "results": [
        {"id": "mem", "content": f"plan costs {mem}", "source": "memory",
         "score": 0.88, "rank": 1, "selected": True}]})
    store.log_event(rid, "context.block",
                    {"source": "memory", "key": "mem",
                     "content": f"plan costs {mem}", "order": 0})
    store.log_event(rid, "prompt.assembled",
                    {"system": "Answer from context.",
                     "messages": [{"role": "user", "content": "Pro price?"}]})
    store.log_event(rid, "model.response", {"response": ans})
    store.finish_run(rid, "ok")

# ---- 1. Token diff -------------------------------------------------
mk_run("run-a", "You are a billing agent. Use the July pricing sheet.",
       "What does the Pro plan cost?", "price is $19/mo.")
mk_run("run-b", "You are a billing agent.",
       "What does the Pro tier cost right now?", "price is $29/mo.")
res = diff_runs(store, "run-a", "run-b")
ps = [s for s in res.sections if s.name == "prompt" and s.changed]
assert ps, "expected changed prompt section"
td = ps[0].details[0].get("token_diff", {})
assert td.get("ops") and td["removed_count"] > 0 and td["added_count"] > 0
print("[OK] token diff:", td["removed_count"], "removed,", td["added_count"], "added spans")

# ---- 2. scored causes ----------------------------------------------
r2 = diff_runs(store, "good", "bad1")
assert r2.scored_causes, "expected scored causes"
confs = [c["confidence"] for c in r2.scored_causes]
assert confs == sorted(confs, reverse=True), "must be ranked desc"
assert all(0.0 <= c <= 1.0 for c in confs)
assert [c["message"] for c in r2.scored_causes] == r2.likely_causes
print("[OK] scored_causes:", [(c["confidence"], c["message"][:50]) for c in r2.scored_causes])

# ---- 3. multi-run -----------------------------------------------------
multi = diff_runs_multi(store, "good", ["bad1", "bad2"])
assert multi["baseline"] == "good" and multi["candidates"] == ["bad1", "bad2"]
assert len(multi["comparisons"]) == 2 and multi["common_causes"]
print("[OK] diff_runs_multi common_causes:", multi["common_causes"])

# ---- 4. JSON-serializable ----------------------------------------------
assert '"common_causes"' in json.dumps(multi)
print("[OK] multi result JSON-serializable")

# ---- 5. Server endpoints ----------------------------------------------
os.environ["AGENT_DEVTOOLS_DB"] = DB
try:
    from fastapi.testclient import TestClient
    import importlib
    import agent_devtools.server.main as m
    importlib.reload(m)
    c = TestClient(m.app)
    r = c.get("/api/diff/multi", params={"baseline": "good", "candidates": "bad1,bad2"})
    assert r.status_code == 200 and r.json()["common_causes"]
    print("[OK] /api/diff/multi:", r.status_code, len(r.json()["common_causes"]), "common causes")
    r2 = c.get("/api/diff", params={"a": "good", "b": "bad1"})
    assert r2.status_code == 200 and "scored_causes" in r2.json()
    print("[OK] /api/diff returns scored_causes")
    r3 = c.get("/api/diff", params={"a": "run-a", "b": "run-b"})
    assert r3.status_code == 200
except ImportError as e:
    print("[SKIP] fastapi testclient unavailable:", e)

print("ALL NEW DIFF FEATURE TESTS PASSED")