"""
Run two Atlas sessions end-to-end and record detailed agent-devtools traces.

This is the "incident reproduction" script. It runs the SAME LangGraph agent
against the same user question twice, but with different memory state:

  * ``--mode fresh``  -- memory starts empty; the agent *learns* the current
    price ($29/mo) from the source doc. This is the correct behavior.
  * ``--mode stale``  -- memory already holds an old cached price ($19/mo,
    captured before the July 1st change). The retriever ranks it first and
    the agent re-commits and quotes it. THIS IS THE BUG.

Both runs are fully deterministic (no API key), so the exact same event
timeline is produced on every execution -- which is what makes them safe to
replay and diff in Agent DevTools.

Usage:

    python run_session.py --mode fresh
    python run_session.py --mode stale
    agent-devtools serve          # then open the UI and compare the two runs
"""

from __future__ import annotations

import argparse
import os
import sys

# Make the SDK importable when running from the examples dir.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "packages", "python-sdk"))

from agent_devtools import trace

from agent import SAVED_MEMORY, build_atlas_graph

USER_QUESTION = "What does my Pro plan cost right now?"


def run_session(mode: str, run_id: str) -> str:
    """Run one Atlas session and return the final answer."""
    if mode == "fresh":
        memory = {}
    elif mode == "stale":
        memory = dict(SAVED_MEMORY)
    else:
        raise ValueError(f"unknown mode: {mode}")

    with trace.run("atlas-billing-agent", run_id=run_id, metadata={"mode": mode}) as run:
        run.input(USER_QUESTION, mode=mode)
        graph = build_atlas_graph(run=run, memory=memory)
        result = graph.invoke(
            {"query": USER_QUESTION, "messages": []},
            config={"recursion_limit": 20},
        )
        answer = result["answer"]
        run.output(answer, final=True)
        return answer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an Atlas session.")
    parser.add_argument("--mode", choices=["fresh", "stale"], default="fresh")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    run_id = args.run_id or f"atlas-{args.mode}-{os.getpid()}"
    answer = run_session(args.mode, run_id)
    print(f"[{run_id}] mode={args.mode}")
    print(f"  question: {USER_QUESTION}")
    print(f"  answer:   {answer}")


if __name__ == "__main__":
    main()