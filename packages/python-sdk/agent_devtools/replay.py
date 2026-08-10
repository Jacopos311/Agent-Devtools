"""
Deterministic Replay engine.

Re-executes a recorded run purely from its append-only event log -- no
network, no LLM, no user code -- and reports whether the recorded behavior
is *self-consistent* (completed), *internally contradictory* (diverged),
or recorded a failure (failed).

"Deterministic" here means: the parts of a run that are fully determined
by the recorded events are re-derived from scratch, and the recorded log
is checked against that re-derivation:

- Memory lifecycle: ``memory.write`` / ``memory.update`` /
  ``memory.delete`` are applied to a fresh store in sequence order.
  ``memory.update`` is verified against the value the write chain
  established, and ``memory.read`` values are verified against that same
  chain. A read that returns a value the chain never wrote, or an update
  whose recorded ``old_value`` disagrees with the replayed state, is a
  divergence -- the classic stale-memory bug made visible.
- Retrieval: candidate ranks are re-derived from scores, and the selected
  set is checked for score monotonicity (no rejected candidate may score
  strictly higher than a selected one).
- Tools: every ``tool.call`` must be matched by a ``tool.result`` or
  ``tool.error``; unmatched calls are reported as notes.
- CI debug assertions: recorded ``assertion.passed`` / ``assertion.failed``
  events are replayed. Any recorded ``assertion.failed``, or a run that
  finished with status ``error``, marks the replay as **failed**.

A **completed** replay means the recorded log is internally consistent: a
deterministic re-run with the same inputs would have produced the same
event chain. A **diverged** replay names the exact event where the log
contradicts itself. A **failed** replay means the run recorded a failure
(debug assertion or error).

This is deliberately separate from framework-level "re-run the graph"
replays (see ``examples/langgraph-memory-agent/verify_traces.py``): those
require the agent's code and a deterministic model. This engine works on
*any* recorded run, in the UI or via the HTTP API, with no user code.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


def _num(value: Any) -> Optional[float]:
    """Coerce a value to float, or None if it isn't numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _short(value: Any, limit: int = 120) -> str:
    """Best-effort one-line preview of a payload value for step details."""
    if value is None:
        return "None"
    text = value if isinstance(value, str) else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


@dataclass
class ReplayReport:
    """Result of a deterministic replay of one run.

    ``status`` is one of:

    - ``completed`` -- every recorded event is internally consistent; a
      deterministic re-run would reproduce the recorded timeline.
    - ``diverged`` -- at least one recorded event contradicts the replay
      (stale memory read, memory update on a different value, retrieval
      rank/score contradiction, etc.). ``evidence`` names each break.
    - ``failed`` -- the run recorded a failure (``assertion.failed`` or a
      terminal run status of ``error``).
    """

    replay_id: str
    run_id: str
    created_at: float
    status: str
    summary: str
    events_replayed: int
    steps: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    assertions: dict = field(default_factory=lambda: {"passed": 0, "failed": 0})
    output: Any = None
    memory_final: dict = field(default_factory=dict)
    run_status: str = ""

    def to_dict(self) -> dict:
        return {
            "replay_id": self.replay_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "status": self.status,
            "summary": self.summary,
            "events_replayed": self.events_replayed,
            "steps": self.steps,
            "evidence": self.evidence,
            "assertions": self.assertions,
            "output": self.output,
            "memory_final": self.memory_final,
            "run_status": self.run_status,
        }


class ReplayEngine:
    """Deterministically re-execute a run from its recorded event log."""

    def __init__(self, store) -> None:
        self.store = store

    # -- public API ---------------------------------------------------

    def replay(self, run_id: str) -> ReplayReport:
        """Run a deterministic replay of ``run_id`` and build its report."""
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"run '{run_id}' not found")
        events = self.store.get_events(run_id)
        return self._build_report(run, events)

    # -- core replay --------------------------------------------------

    def _build_report(self, run: dict, events) -> ReplayReport:
        steps: list[dict] = []
        evidence: list[dict] = []
        memory: dict[str, Any] = {}
        assertions = {"passed": 0, "failed": 0}
        output: Any = None
        pending_tools: list[tuple[int, str]] = []  # (seq, name) of open tool.call

        for e in events:
            payload = e.payload or {}
            step: dict = {"seq": e.seq, "type": e.type, "status": "ok", "detail": None}

            if e.type == "memory.write":
                key = payload.get("key")
                value = payload.get("value")
                memory[key] = value
                step["detail"] = f"memory.write {key} = {_short(value)}"
            elif e.type == "memory.update":
                key = payload.get("key")
                prev = memory.get(key)
                recorded_old, recorded_new = payload.get("old_value"), payload.get("new_value")
                if key in memory and prev != recorded_old:
                    step["status"] = "mismatch"
                    step["detail"] = (
                        f"memory.update {key}: recorded old_value {_short(recorded_old)} "
                        f"!= replayed state {_short(prev)}"
                    )
                    evidence.append({
                        "kind": "memory.update.old_value",
                        "seq": e.seq,
                        "severity": "divergence",
                        "message": (
                            f"memory.update for '{key}' was applied to a different value "
                            f"than the replay chain established."
                        ),
                        "expected": prev,
                        "actual": recorded_old,
                    })
                elif key not in memory and recorded_old is not None:
                    step["status"] = "note"
                    step["detail"] = (
                        f"memory.update {key}: key not in replay chain "
                        f"(external memory seed) -- cannot verify old_value"
                    )
                    evidence.append({
                        "kind": "memory.update.external",
                        "seq": e.seq,
                        "severity": "note",
                        "message": (
                            f"memory.update for '{key}' targeted memory that the replay "
                            f"chain never wrote (external seed); old_value not reproducible."
                        ),
                        "expected": None,
                        "actual": None,
                    })
                memory[key] = recorded_new
                step["detail"] = step["detail"] or f"memory.update {key} -> {_short(recorded_new)}"

            elif e.type == "memory.delete":
                key = payload.get("key")
                if key not in memory:
                    step["status"] = "note"
                    step["detail"] = f"memory.delete {key}: key absent from replay chain"
                    evidence.append({
                        "kind": "memory.delete.missing",
                        "seq": e.seq,
                        "severity": "note",
                        "message": f"memory.delete for '{key}' removed a key the replay chain never wrote.",
                        "expected": None,
                        "actual": None,
                    })
                memory.pop(key, None)

            elif e.type == "memory.read":
                key = payload.get("key")
                recorded_value = payload.get("value")
                if key in memory:
                    if memory[key] != recorded_value:
                        step["status"] = "mismatch"
                        step["detail"] = (
                            f"memory.read {key}: recorded {_short(recorded_value)} "
                            f"!= replayed state {_short(memory[key])}"
                        )
                        evidence.append({
                            "kind": "memory.read.stale",
                            "seq": e.seq,
                            "severity": "divergence",
                            "message": (
                                f"The run read '{key}' as {_short(recorded_value)}, but the replay "
                                f"of this run's own write chain had {_short(memory[key])} at that "
                                f"point -- the agent read stale or externally-mutated memory."
                            ),
                            "expected": memory[key],
                            "actual": recorded_value,
                        })
                    else:
                        step["detail"] = f"memory.read {key} matched replayed write chain"
                else:
                    step["status"] = "note"
                    step["detail"] = (
                        f"memory.read {key}: key not in replay chain (external memory) -- "
                        f"cannot verify value"
                    )
                    evidence.append({
                        "kind": "memory.read.external",
                        "seq": e.seq,
                        "severity": "note",
                        "message": (
                            f"memory.read for '{key}' read from a store the replay chain never "
                            f"wrote to; its value is not reproducible from this log."
                        ),
                        "expected": None,
                        "actual": None,
                    })
            elif e.type == "retrieval.result":
                step = self._replay_retrieval(step, payload, evidence)

            elif e.type == "tool.call":
                pending_tools.append((e.seq, payload.get("name")))
                step["detail"] = f"tool.call {_short(payload.get('name'))} opened"

            elif e.type in ("tool.result", "tool.error"):
                if pending_tools:
                    pending_tools.pop()
                step["detail"] = f"{e.type} closed pending tool call"

            elif e.type == "model.response":
                output = payload.get("response")
                step["detail"] = "replayed recorded model output"

            elif e.type == "assertion.passed":
                assertions["passed"] += 1
                step["detail"] = f"replayed assertion '{payload.get('name')}' (passed)"

            elif e.type == "assertion.failed":
                assertions["failed"] += 1
                step["status"] = "failed"
                name = payload.get("name") or "?"
                details = payload.get("details")
                step["detail"] = f"replayed assertion '{name}' (failed in recorded run)"
                evidence.append({
                    "kind": "assertion.failed",
                    "seq": e.seq,
                    "severity": "failure",
                    "message": (
                        f"The recorded run contains failed debug assertion '{name}'"
                        f"{': ' + str(details) if details else ''}."
                    ),
                    "expected": {"passed": True},
                    "actual": {"passed": False, "name": name, "details": details},
                })

            elif e.type == "user.input":
                step["detail"] = "replayed user message"

            elif e.type == "context.block":
                step["detail"] = (
                    f"replayed context block '{payload.get('key') or payload.get('source')}'"
                )

            elif e.type == "prompt.assembled":
                step["detail"] = "replayed assembled prompt"

            elif e.type == "state.snapshot":
                step["detail"] = "replayed state snapshot"

            else:
                step["detail"] = f"replayed {e.type}"

            steps.append(step)

        # Any tool.call that was never closed by tool.result / tool.error.
        for seq, name in pending_tools:
            evidence.append({
                "kind": "tool.dangling",
                "seq": seq,
                "severity": "note",
                "message": (
                    f"tool.call '{_short(name)}' (event #{seq}) has no matching tool.result "
                    f"or tool.error -- the recorded capture is incomplete."
                ),
                "expected": {"state": "closed"},
                "actual": {"state": "open"},
            })
            steps.append({
                "seq": seq,
                "type": "tool.dangling",
                "status": "note",
                "detail": f"tool.call '{_short(name)}' never closed",
            })
        # -- status determination ---------------------------------------
        run_status = run.get("status", "")
        has_failure = assertions["failed"] > 0 or run_status == "error"
        has_divergence = any(ev["severity"] == "divergence" for ev in evidence)
        if has_failure:
            status = "failed"
        elif has_divergence:
            status = "diverged"
        else:
            status = "completed"

        failure_ev = [ev for ev in evidence if ev["severity"] == "failure"]
        divergence_ev = [ev for ev in evidence if ev["severity"] == "divergence"]
        if status == "failed":
            if failure_ev:
                summary = (
                    f"Replay failed: the run recorded {assertions['failed']} failed debug "
                    f"assertion(s). The recorded behavior is reproducible, but it is broken."
                )
            else:
                summary = f"Replay failed: the recorded run ended with status '{run_status}'."
        elif status == "diverged":
            kinds = sorted({ev["kind"] for ev in divergence_ev})
            summary = (
                f"Replay diverged at {len(divergence_ev)} event(s): the recorded log is "
                f"internally inconsistent "
                f"({', '.join(kinds)}). A deterministic re-run would not reproduce it."
            )
        else:
            summary = (
                f"Replay completed: {len(steps)} events replayed with no divergence. "
                f"The recorded run is deterministically self-consistent."
            )

        return ReplayReport(
            replay_id=f"replay-{uuid.uuid4().hex[:12]}",
            run_id=run["id"],
            created_at=time.time(),
            status=status,
            summary=summary,
            events_replayed=len(steps),
            steps=steps,
            evidence=evidence,
            assertions=assertions,
            output=output,
            memory_final=memory,
            run_status=run_status,
        )

    def _replay_retrieval(self, step: dict, payload: dict, evidence: list) -> dict:
        """Verify recorded retrieval ranks against scores and selection against
        score monotonicity. Returns the step dict (possibly marked mismatch)."""
        results = payload.get("results") or []
        scored = [
            (i, r, _num(r.get("score")))
            for i, r in enumerate(results)
            if _num(r.get("score")) is not None
        ]
        mismatches = 0

        # 1. Ranks must be the descending-score order.
        for pos, (_, r, _score) in enumerate(sorted(scored, key=lambda t: -t[2])):
            recorded = r.get("rank")
            expected_rank = pos + 1
            if recorded is not None and isinstance(recorded, (int, float)) and not isinstance(recorded, bool):
                if int(recorded) != expected_rank:
                    mismatches += 1
                    evidence.append({
                        "kind": "retrieval.rank",
                        "seq": step["seq"],
                        "severity": "divergence",
                        "message": (
                            f"Retrieval candidate '{r.get('id', '(no id)')}' was recorded at "
                            f"rank {int(recorded)}, but its score orders it at rank "
                            f"{expected_rank} -- ranks contradict scores."
                        ),
                        "expected": {"rank": expected_rank},
                        "actual": {"rank": int(recorded), "id": r.get("id")},
                    })

        # 2. Selection must be score-monotone: no rejected (non-filtered)
        #    candidate may score strictly higher than a selected one.
        selected_scores = [t[2] for t in scored if t[1].get("selected") is True]
        rejected_scores = [
            t[2] for t in scored
            if t[1].get("selected") is False and not t[1].get("filtered")
        ]
        if selected_scores and rejected_scores:
            lowest_selected = min(selected_scores)
            highest_rejected = max(rejected_scores)
            if highest_rejected > lowest_selected:
                mismatches += 1
                evidence.append({
                    "kind": "retrieval.selection",
                    "seq": step["seq"],
                    "severity": "divergence",
                    "message": (
                        f"Retrieval selected a candidate scoring {lowest_selected} while "
                        f"rejecting one scoring {highest_rejected} -- selection is not "
                        f"consistent with scores."
                    ),
                    "expected": {"rule": "selected set is score-monotone"},
                    "actual": {"selected_min": lowest_selected, "rejected_max": highest_rejected},
                })

        if mismatches:
            step["status"] = "mismatch"
            step["detail"] = f"retrieval: {len(results)} candidates replayed, {mismatches} contradiction(s)"
        else:
            step["detail"] = f"retrieval: {len(results)} candidates replayed; ranks/scores consistent"
        return step
