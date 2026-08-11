"""Verify the Regression workflow: N-run regression analysis (Task 1).

Covers:
  - detect_regression() classification (regression / suspicious / normal)
  - /api/regression endpoint
  - multi-run comparison with >= 3 runs
  - assertions diff section
  - model/prompt configuration diff (config_diff)

Run:
    python3 test_regression.py
"""
import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SDK = os.path.join(_REPO_ROOT, "packages", "python-sdk")
if _SDK not in sys.path:
    sys.path.insert(0, _SDK)

from agent_devtools import TraceStore, detect_regression, diff_runs, diff_runs_multi  # noqa: E402

DB = os.path.join(tempfile.mkdtemp(), "regression.db")
store = TraceStore(DB)


def mk_run(run_id, scope=None, price="$29/mo", answer=None, mem=True,
           denied=False, failed_assertion=None, model=None, stale_bump=False):
    """Build a small refund-agent run. ``scope`` tenants: A (good) or B (leak)."""
    store.create_run(run_id, "refund-agent",
                     {"scope": {"tenant_id": scope}} if scope else None)
    store.log_event(run_id, "user.input", {"message": "Pro price?"})
    store.log_event(run_id, "retrieval.query", {"query": "Pro price"})

    leaked = (scope == "A" and price == "$19/mo")  # B-tagged chunk pulled into an A run
    if denied:
        store.log_event(run_id, "retrieval.result", {"results": [
            {"id": "doc", "content": "Pro costs $29/mo", "score": 0.91, "rank": 1,
             "selected": False, "outcome": "rejected_permission",
             "denial_reason": "acl: user lacks doc access"},
        ]})
    else:
        store.log_event(run_id, "retrieval.result", {"results": [
            {"id": "mem", "content": f"plan costs {price}", "score": 0.9,
             "rank": 1, "selected": True,
             **({"tenant_id": "B"} if leaked else {})},
        ]})

    if mem:
        store.log_event(run_id, "memory.write",
                        {"key": "pricing_summary", "value": f"plan costs {price}",
                         "created_at": 1.0, "version": 1})
        store.log_event(run_id, "memory.read",
                        {"key": "pricing_summary", "value": f"plan costs {price}",
                         "observed_at": 2.0, "version": 1})
        if stale_bump:
            # Memory changed *after* the decision-time read: the agent decided
            # from $19/mo while the store now holds $29/mo (stale_after_run).
            store.log_event(run_id, "memory.update",
                            {"key": "pricing_summary",
                             "old_value": f"plan costs {price}",
                             "new_value": "plan costs $29/mo",
                             "updated_at": 3.0, "version": 2})
    store.log_event(run_id, "context.block",
                    {"source": "memory", "key": "mem",
                     "content": f"plan costs {price}", "order": 0,
                     **({"tenant_id": "B"} if leaked else {})})

    payload = {"system": "You are a billing agent.", "messages": [
        {"role": "user", "content": "Pro price?"}], "context": ["mem"]}
    if model:
        payload["model"] = model
        payload["temperature"] = 0.7
    store.log_event(run_id, "prompt.assembled", payload)

    store.log_event(run_id, "model.response", {"response": answer or f"Pro costs {price}."})
    store.log_event(run_id, "assertion.passed", {"name": "answer mentions price"})
    if failed_assertion:
        store.log_event(run_id, "assertion.failed",
                        {"name": failed_assertion, "details": "stale price leaked"})
    store.finish_run(run_id, "ok")


# --- Dataset: 3+ runs ---------------------------------------------------
mk_run("good", scope="A", price="$29/mo", answer="Pro costs $29/mo.")
mk_run("bad-stale", scope="A", price="$19/mo", answer="Pro costs $19/mo.",
       stale_bump=True, failed_assertion="no stale pricing mentioned")
mk_run("bad-tenant-b", scope="A", price="$19/mo", answer="Pro costs $19/mo.")
# Divergent output but nothing causal changed -> no confirmed cause (suspicious).
mk_run("bad-susp", scope="A", price="$29/mo", answer="The Pro plan costs $29/mo today.")

# --- 1. detect_regression classification -------------------------------
print("=== 1. detect_regression ===")
rep = detect_regression(store, "good", ["good", "bad-stale", "bad-tenant-b", "bad-susp"])
d = rep.to_dict()
assert d["baseline"] == "good" and d["candidates"] == ["bad-stale", "bad-tenant-b", "bad-susp"]
assert d["statuses"]["bad-stale"] == "regression", d["statuses"]
assert d["statuses"]["bad-tenant-b"] == "regression", d["statuses"]
assert d["statuses"]["bad-susp"] == "suspicious", d["statuses"]

findings = {f["run_id"]: f for f in d["findings"]}
assert findings["bad-stale"]["output_changed"] is True
assert findings["bad-stale"]["scored_causes"], "expected scored cause confirming the change reached the answer"
assert findings["bad-stale"]["evidence_chains"], "expected evidence chain"
assert findings["bad-tenant-b"]["scope_mismatches"], "expected cross-scope mismatch"
assert findings["bad-stale"]["stale_memory"], "expected stale memory in temporal view"
print("[OK] statuses:", d["statuses"])
print("[OK] evidence:", {k: len(v) for k, v in {
    "scored_causes": findings["bad-stale"]["scored_causes"],
    "evidence_chains": findings["bad-stale"]["evidence_chains"],
    "stale_memory": findings["bad-stale"]["stale_memory"]}.items()})
# --- 2. two-run diff now carries assertions + config diff ---------------
print("\n=== 2. assertions + model-config diff sections ===")
mk_run("cfg-a", scope="A", price="$29/mo", answer="Pro costs $29/mo.", model="llama-3.3-70b")
mk_run("cfg-b", scope="A", price="$29/mo", answer="Pro costs $29/mo.", model="gpt-4o")
res = diff_runs(store, "cfg-a", "cfg-b")
by_name = {s.name: s for s in res.sections}
assert by_name["prompt"].changed, "config_diff should mark the prompt changed"
detail = by_name["prompt"].details[0]
assert detail.get("config_diff") and detail["config_diff"][0]["key"] == "model", detail
print("[OK] config_diff:", detail["config_diff"])

res2 = diff_runs(store, "good", "bad-stale")
by_name2 = {s.name: s for s in res2.sections}
assert "assertions" in by_name2, "assertions section should be present"
assert by_name2["assertions"].changed, "assertion failure counts differ"
print("[OK] assertions diff:", by_name2["assertions"].details[0])

# --- 3. multi-run comparison with >= 3 runs ----------------------------
print("\n=== 3. multi-run comparison ===")
multi = diff_runs_multi(store, "good", ["bad-stale", "bad-tenant-b", "bad-susp"])
assert len(multi["comparisons"]) == 3
multi2 = diff_runs_multi(store, "good", ["bad-stale", "bad-tenant-b"])
assert multi2["common_causes"], "expected a common cause across the two regression runs"
print("[OK] multi-run:", len(multi["comparisons"]), "comparisons,",
      len(multi2["common_causes"]), "common cause(s) across the regressions")

# --- 4. server endpoints ------------------------------------------------
print("\n=== 4. server endpoints ===")
os.environ["AGENT_DEVTOOLS_DB"] = DB
try:
    from fastapi.testclient import TestClient
    import importlib
    import agent_devtools.server.main as m
    importlib.reload(m)
    c = TestClient(m.app)

    r = c.get("/api/regression",
              params={"baseline": "good", "candidates": "bad-stale,bad-tenant-b,bad-susp"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["statuses"]["bad-stale"] == "regression"
    assert len(body["findings"]) == 3
    print("[OK] /api/regression:", r.status_code, body["statuses"])

    r2 = c.get("/api/regression", params={"baseline": "good", "candidates": "nope"})
    assert r2.status_code == 404
    print("[OK] /api/regression 404 for missing candidate")

    r3 = c.get("/api/diff/multi",
               params={"baseline": "good", "candidates": "bad-stale,bad-tenant-b"})
    assert r3.status_code == 200 and len(r3.json()["comparisons"]) == 2
    print("[OK] /api/diff/multi with 3 runs:", r3.status_code)

    r4 = c.get("/api/diff", params={"a": "good", "b": "bad-stale"})
    assert r4.status_code == 200 and "evidence_chains" in r4.json()
    print("[OK] /api/diff returns evidence_chains for drill-down")
except ImportError as e:
    print("[SKIP] fastapi testclient unavailable:", e)

print("\nALL REGRESSION TESTS PASSED")
print("[OK] cross-scope evidence:", findings["bad-tenant-b"]["scope_mismatches"][0]["message"])