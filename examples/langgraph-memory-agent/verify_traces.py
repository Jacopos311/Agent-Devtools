"""
Verify the Atlas traces landed in the store, and (optionally) replay the
deterministic graph from a run's recorded events.

This gives you a scriptable "deterministic replay" check: because both
modes are fully deterministic (no API key), re-running the same mode with
the same seed reproduces the exact same event timeline every time.

Usage:

    python run_session.py --mode fresh --run-id atlas-fresh-demo
    python run_session.py --mode stale --run-id atlas-stale-demo
    python verify_traces.py atlas-fresh-demo atlas-stale-demo
"""

from __future__ import annotations

import argparse
import os
import sys

# Make the SDK importable when running from the examples dir.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "packages", "python-sdk"))

from agent_devtools import TraceStore, diff_runs
from agent_devtools.explain import explain_retrieval

from agent import SAVED_MEMORY, build_atlas_graph
from run_session import USER_QUESTION


def _summarize_events(events) -> dict:
    counts: dict[str, int] = {}
    for e in events:
        counts[e.type] = counts.get(e.type, 0) + 1
    return counts


def _latest_answer(events) -> str:
    for e in reversed(events):
        if e.type == "model.response":
            payload = e.payload or {}
            resp = payload.get("response", "")
            if payload.get("final"):
                return resp
    return ""


def verify_run(store: TraceStore, run_id: str) -> bool:
    """Check that a run has the expected events and a final answer."""
    run = store.get_run(run_id)
    if run is None:
        print(f"  MISSING run {run_id!r} in {store.db_path}")
        return False

    events = store.get_events(run_id)
    counts = _summarize_events(events)
    answer = _latest_answer(events)

    expected = [
        "user.input",
        "state.snapshot",
        "retrieval.query",
        "retrieval.result",
        "memory.write",
        "context.block",
        "prompt.assembled",
        "model.response",
        "tool.call",
        "tool.result",
    ]
    # The fresh run starts with empty memory, so it never reads a memory
    # candidate. Only the stale run (which has a memory candidate) performs
    # a memory.read.
    mode = (run or {}).get("metadata", {}).get("mode", "fresh")
    if mode == "stale":
        expected.append("memory.read")
    missing = [t for t in expected if counts.get(t, 0) == 0]
    ok = True
    if missing:
        print(f"  run {run_id}: missing event types: {missing}")
        ok = False
    if not answer:
        print(f"  run {run_id}: no final answer recorded")
        ok = False

    print(f"  run {run_id} ({run.get('agent_name')}) status={run.get('status')} events={len(events)}")
    print(f"    answer: {answer}")
    return ok


def replay_run(run_id: str, mode: str) -> str:
    """Deterministic replay: rebuild the graph (same memory seed) and invoke
    with the same query. Because the graph never touches the network, this
    reproduces the recorded timeline exactly."""
    memory = {} if mode == "fresh" else dict(SAVED_MEMORY)
    graph = build_atlas_graph(run=None, memory=memory)
    result = graph.invoke(
        {"query": USER_QUESTION, "messages": []},
        config={"recursion_limit": 20},
    )
    return result["answer"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Atlas traces and replay.")
    parser.add_argument("run_ids", nargs="+", help="Run IDs to verify (e.g. atlas-fresh-demo atlas-stale-demo)")
    parser.add_argument("--replay", action="store_true", help="Also deterministically replay each run's mode")
    args = parser.parse_args()

    store = TraceStore()
    print(f"db: {store.db_path}\n")

    all_ok = True
    for run_id in args.run_ids:
        ok = verify_run(store, run_id)
        all_ok = all_ok and ok
        if args.replay:
            run = store.get_run(run_id)
            mode = (run or {}).get("metadata", {}).get("mode", "fresh")
            answer = replay_run(run_id, mode)
            print(f"    replay answer: {answer}")

    if len(args.run_ids) >= 2:
        a, b = args.run_ids[0], args.run_ids[1]
        print(f"\nDiff {a} (good) vs {b} (bad):")
        diff = diff_runs(store, a, b)
        for cause in diff.likely_causes:
            print(f"  likely cause: {cause}")
        for sentence in diff.narrative:
            print(f"  - {sentence}")

        print(f"\nRetrieval explanation for {b}:")
        events = store.get_events_by_types(b, ["retrieval.query", "retrieval.result"])
        for exp in explain_retrieval(events):
            print(f"  query: {exp['query']}")
            print(f"  summary: {exp['summary']}")

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()