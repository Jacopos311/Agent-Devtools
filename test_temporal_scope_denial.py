"""
Verify the Phase 2 / 3 / 4 / 7 / 8 additions:

- Temporal Memory view (observed-at-decision-time vs current, stale detection)
- Retrieval Denial outcomes (explicit, never inferred)
- Scope / isolation debugging (cross-tenant, only when evidenced)
- Causal evidence chains (evidence through memory -> retrieval -> context ->
  prompt -> output)
- Prompt token-count clarity (estimate vs exact, delta)

Run with:
    python3 test_temporal_scope_denial.py
"""
import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SDK = os.path.join(_REPO_ROOT, "packages", "python-sdk")
if _SDK not in sys.path:
    sys.path.insert(0, _SDK)

from agent_devtools.store import TraceStore
from agent_devtools.memory_view import memory_view
from agent_devtools.scope import detect_scope_mismatches, scope_from_metadata
from agent_devtools.explain import explain_retrieval, classify_outcome
from agent_devtools.diff import diff_runs

DB = os.path.join(tempfile.mkdtemp(), "tsd.db")
store = TraceStore(DB)


def mk_run(run_id, status="ok", meta=None, events=()):
    store.create_run(run_id, "agent", meta)
    for et, payload in events:
        store.log_event(run_id, et, payload)
    store.finish_run(run_id, status)


def refresh(run_id):
    return store.get_events(run_id)


# ---------------------------------------------------------------------------
# 1. Temporal Memory
# ---------------------------------------------------------------------------
print("=== 1. temporal memory ===")

mk_run("tm-stale", events=[
    ("memory.write", {"key": "plan_price", "value": "$19/mo", "created_at": 1.0, "version": 1}),
    ("memory.read", {"key": "plan_price", "value": "$19/mo", "observed_at": 2.0}),
    ("memory.update", {"key": "plan_price", "old_value": "$19/mo", "new_value": "$29/mo",
                       "updated_at": 3.0, "version": 2}),
])
v = memory_view(refresh("tm-stale"))
k = v["keys"]["plan_price"]
assert k["status"] == "stale_after_run", k
assert k["observed"]["value"] == "$19/mo" and k["current"]["value"] == "$29/mo"
assert k["historical_available"] is True
assert v["stale"] == ["plan_price"]
print("[OK] stale_after_run observed=$19/mo -> current=$29/mo")

mk_run("tm-consistent", events=[
    ("memory.write", {"key": "addr", "value": "Rome"}),
    ("memory.read", {"key": "addr", "value": "Rome"}),
])
assert memory_view(refresh("tm-consistent"))["keys"]["addr"]["status"] == "consistent"
print("[OK] consistent")

mk_run("tm-writeonly", events=[("memory.write", {"key": "x", "value": "1"})])
k = memory_view(refresh("tm-writeonly"))["keys"]["x"]
assert k["status"] == "write_only" and k["historical_available"] is False
assert k["observed"] is None
print("[OK] write_only with historical state unavailable")

mk_run("tm-observed", events=[("memory.read", {"key": "seed", "value": "old"})])
k = memory_view(refresh("tm-observed"))["keys"]["seed"]
assert k["status"] == "observed_only" and k["historical_available"] is True
print("[OK] observed_only (external seed)")

mk_run("tm-deleted", events=[
    ("memory.read", {"key": "tmp", "value": "v"}),
    ("memory.delete", {"key": "tmp", "deleted_at": 5.0}),
])
assert memory_view(refresh("tm-deleted"))["keys"]["tmp"]["status"] == "deleted_after_run"
print("[OK] deleted_after_run")

mk_run("tm-empty")
assert memory_view(refresh("tm-empty"))["keys"] == {}
print("[OK] empty run -> no fabricated memory")

# ---------------------------------------------------------------------------
# 2. Retrieval Denials (explicit, never inferred)
# ---------------------------------------------------------------------------
print("\n=== 2. retrieval denial outcomes ===")
ev = [type("E", (), {"type": "retrieval.result", "payload": {"results": [
    {"id": "m1", "content": "c", "score": 0.94, "selected": False,
     "denied": True, "denial_reason": "tenant_scope mismatch"},
    {"id": "m2", "content": "d", "score": 0.94, "selected": True},
    {"id": "m3", "content": "e", "score": 0.2, "rank": 2, "selected": False,
     "threshold": 0.8},
]}})]
exps = explain_retrieval(ev)
by_id = {r["id"]: r for r in exps[0]["results"]}
assert by_id["m1"]["outcome"] == "rejected_permission"
assert "tenant_scope mismatch" in by_id["m1"]["reason"]
assert by_id["m2"]["outcome"] == "selected"
assert by_id["m3"]["outcome"] == "rejected_threshold"
assert classify_outcome({"id": "n", "score": 0.9, "selected": True, "threshold": 0.8}) == "selected"
assert classify_outcome({"id": "n", "selected": True}) == "selected"
print("[OK] permission denial + selected + threshold classification")

ev2 = [type("E", (), {"type": "retrieval.result", "payload": {"results": [
    {"id": "a", "no_match": True, "selected": False}]}})]
assert explain_retrieval(ev2)[0]["results"][0]["outcome"] == "no_match"
print("[OK] no_match outcome")

# ---------------------------------------------------------------------------
# 3. Scope / isolation (only when evidenced)
# ---------------------------------------------------------------------------
print("\n=== 3. scope isolation ===")
mk_run("scope-x", meta={"scope": {"tenant_id": "A"}}, events=[
    ("memory.read", {"key": "doc", "value": "v", "tenant_id": "B"}),
    ("retrieval.result", {"results": [
        {"id": "chunk", "content": "c", "tenant_id": "B"}]}),
])
expected = scope_from_metadata({"scope": {"tenant_id": "A"}})
mm = detect_scope_mismatches(refresh("scope-x"), expected_scope=expected)
assert len(mm) == 2, mm
kinds = {m["kind"] for m in mm}
assert kinds == {"memory.read", "retrieval.result"}
for m in mm:
    assert m["field"] == "tenant_id" and m["expected"] == "A" and m["actual"] == "B"
    assert "Cross-scope" in m["message"]
print("[OK] cross-tenant memory + retrieval mismatches detected")

mk_run("scope-none", events=[("memory.read", {"key": "doc", "value": "v", "tenant_id": "B"})])
assert detect_scope_mismatches(refresh("scope-none"), run_metadata={}) == []
assert scope_from_metadata({}) is None
print("[OK] no scope metadata -> no fabricated mismatch")

mk_run("scope-ok", meta={"scope": {"tenant_id": "A"}}, events=[
    ("memory.read", {"key": "doc", "value": "v", "tenant_id": "A"}),
])
assert detect_scope_mismatches(refresh("scope-ok"),
                               expected_scope={"tenant_id": "A"}) == []
print("[OK] matching scope -> no mismatch")

# ---------------------------------------------------------------------------
# 4. Causal evidence chain
# ---------------------------------------------------------------------------
print("\n=== 4. causal evidence chain ===")
mk_run("b-good", events=[
    ("retrieval.result", {"results": [
        {"id": "mem", "content": "plan costs $29/mo", "score": 0.9, "rank": 1, "selected": True}]}),
    ("context.block", {"source": "memory", "key": "mem", "content": "plan costs $29/mo", "order": 0}),
    ("prompt.assembled", {"system": "s", "messages": [{"role": "user", "content": "q"}], "context": ["mem"]}),
    ("model.response", {"response": "The plan costs $29/mo."}),
])
mk_run("b-bad", events=[
    ("retrieval.result", {"results": [
        {"id": "mem", "content": "plan costs $19/mo", "score": 0.9, "rank": 1, "selected": True}]}),
    ("context.block", {"source": "memory", "key": "mem", "content": "plan costs $19/mo", "order": 0}),
    ("prompt.assembled", {"system": "s", "messages": [{"role": "user", "content": "q"}], "context": ["mem"]}),
    ("model.response", {"response": "The plan costs $19/mo."}),
])
d = diff_runs(store, "b-good", "b-bad")
assert d.evidence_chains, "expected evidence chains"
ec = d.evidence_chains[0]
reached = {st["stage"] for st in ec["steps"] if st["status"] == "reached"}
assert {"selected_into_context", "final_prompt", "output"} <= reached, reached
assert ec["broken_at"] is None
assert "token-level attribution" in ec["caveat"] and "not available" in ec["caveat"]
print("[OK] evidence chain reached:", sorted(reached))

mk_run("b-bad2", events=[
    ("retrieval.result", {"results": [
        {"id": "mem", "content": "plan costs $19/mo", "score": 0.9, "rank": 1, "selected": True}]}),
    ("context.block", {"source": "memory", "key": "mem", "content": "plan costs $19/mo", "order": 0}),
    ("prompt.assembled", {"system": "s", "messages": [{"role": "user", "content": "q"}]}),
    ("model.response", {"response": "The plan costs $19/mo."}),
])
dc = diff_runs(store, "b-good", "b-bad2")
ec2 = dc.evidence_chains[0]
assert ec2["broken_at"] == "final_prompt", ec2["broken_at"]
print("[OK] broken chain reported at", ec2["broken_at"])


# ---------------------------------------------------------------------------
# 5. Prompt token clarity
# ---------------------------------------------------------------------------
print("\n=== 5. prompt token clarity ===")
mk_run("t-good", events=[
    ("prompt.assembled", {"system": "You are a billing agent. Use the July sheet.",
                          "messages": [{"role": "user", "content": "Pro price?"}]}),
    ("model.response", {"response": "x"}),
])
mk_run("t-bad", events=[
    ("prompt.assembled", {"system": "You are a billing agent.",
                          "messages": [{"role": "user", "content": "Pro tier price?"}],
                          "usage": {"prompt_tokens": 88, "total_tokens": 91}}),
    ("model.response", {"response": "y"}),
])
td = diff_runs(store, "t-good", "t-bad")
ps = [s for s in td.sections if s.name == "prompt" and s.changed][0]
detail = ps.details[0]
assert detail["token_diff"]["estimate"] is True
assert detail["token_diff"]["method"].startswith("word+whitespace")
tc = detail["token_counts"]
assert tc["estimate"] is True and "delta" in tc
assert tc["recorded"]["bad"]["exact"] is True
assert tc["recorded"]["bad"]["prompt_tokens"] == 88
print("[OK] token estimate flag + exact recorded count (88) + delta", tc["delta"])

mk_run("t-none-good", events=[("prompt.assembled", {"system": "a", "messages": []})])
mk_run("t-none-bad", events=[("prompt.assembled", {"system": "ab", "messages": []})])
tn = diff_runs(store, "t-none-good", "t-none-bad")
pfc = [s for s in tn.sections if s.name == "prompt" and s.changed][0].details[0]
assert pfc["token_counts"]["recorded"]["bad"] is None
print("[OK] no false exact count when trace recorded none")

print("\nALL TEMPORAL / SCOPE / DENIAL / EVIDENCE-CHAIN TESTS PASSED")

