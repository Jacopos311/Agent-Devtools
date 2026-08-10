"""
Behavior Diff -- the killer feature.

Compare a good run and a bad run and explain, in plain language, what
differed: input, retrieved memories, context blocks, the assembled prompt,
tool results, memory events, and the final answer. Where a difference in
context/memory shows up verbatim in the final answer, flag it as a likely
cause instead of just another line in a list of differences.

This is intentionally a heuristic, not a proof. It is meant to point a
developer at the right three lines of a trace instead of forcing them to
diff two JSON blobs by eye.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .store import TraceStore


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _tokenize(text: str) -> list[str]:
    """Split text into tokens (words + whitespace) for diffing."""
    return re.findall(r"\S+|\s+", text or "")


def _diff_tokens(text_a: str, text_b: str) -> dict:
    """Compute a token-level diff between two texts.

    Returns a dict with ``ops`` (a list of added/removed/replaced spans),
    plus counts of changed tokens. This is what powers the "what exactly
    changed in the prompt" view in the Diff tab.

    NOTE: without an exact model tokenizer, the "tokens" here are a
    word+whitespace *estimate*, never an exact model token count. The
    ``estimate`` flag and an ``estimated_counts`` sub-dict make that explicit
    so the UI never presents an estimate as a real token count. When a trace
    records exact token counts (see ``_recorded_token_counts``), those are
    surfaced separately.
    """
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    matcher = difflib.SequenceMatcher(None, tokens_a, tokens_b)
    ops = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = "".join(tokens_a[i1:i2])
        added = "".join(tokens_b[j1:j2])
        ops.append({
            "tag": tag,
            "removed": removed,
            "added": added,
        })
    return {
        "ops": ops,
        "removed_count": sum(1 for op in ops if op["removed"]),
        "added_count": sum(1 for op in ops if op["added"]),
        # Explicit: this is an estimate, not an exact tokenizer count.
        "estimate": True,
        "method": "word+whitespace split estimate (not an exact model tokenizer)",
        "estimated_counts": {
            "a_total_tokens": len(tokens_a),
            "b_total_tokens": len(tokens_b),
            "a_chars": len(text_a or ""),
            "b_chars": len(text_b or ""),
        },
    }


def _recorded_token_counts(prompt_payload: Optional[dict]) -> Optional[dict]:
    """Exact prompt token counts when the trace actually recorded them.

    Reads the optional ``usage`` / ``token_count`` / ``tokens`` payload keys
    and normalizes to ``{prompt_tokens, total_tokens}``. Returns None when no
    exact counts were recorded (never estimates here).
    """
    if not prompt_payload:
        return None
    usage = prompt_payload.get("usage") or {}
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        total = usage.get("total_tokens")
        if prompt_tokens is not None or total is not None:
            return {
                "prompt_tokens": prompt_tokens,
                "total_tokens": total if total is not None else prompt_tokens,
                "exact": True,
                "source": "usage",
            }
    tc = prompt_payload.get("token_count")
    if isinstance(tc, dict):
        pt = tc.get("prompt_tokens")
        if pt is not None:
            return {"prompt_tokens": pt, "total_tokens": pt, "exact": True,
                    "source": "token_count"}
    t = prompt_payload.get("tokens")
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        return {"prompt_tokens": t, "total_tokens": t, "exact": True,
                "source": "tokens"}
    return None



def _prompt_to_text(system: Optional[str], messages: Optional[list]) -> str:
    """Flatten a prompt (system + messages) into a single text for diffing."""
    parts = []
    if system:
        parts.append(f"system: {system}")
    for m in messages or []:
        if isinstance(m, dict):
            role = m.get("role", "message")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(c.get("text", c)) if isinstance(c, dict) else str(c)
                    for c in content
                )
            parts.append(f"{role}: {content}")
        else:
            parts.append(f"message: {m}")
    return "\n".join(parts)


def _latest(events, event_type):
    matches = [e for e in events if e.type == event_type]
    return matches[-1] if matches else None


def _index_context_blocks(events):
    blocks = [e.payload for e in events if e.type == "context.block"]
    by_key = {}
    for i, b in enumerate(blocks):
        key = b.get("key") or f"{b.get('source', 'unknown')}#{i}"
        by_key[key] = {**b, "position": i}
    return by_key


def _index_retrieval_results(events):
    """Flatten every retrieval.result event into {id_or_content: entry}."""
    out = {}
    for e in events:
        if e.type != "retrieval.result":
            continue
        for r in e.payload.get("results", []):
            rid = r.get("id") or r.get("content")
            if rid is None:
                continue
            out[rid] = r
    return out


def _rerank_score(r):
    """Reranker score if the retrieval result carries one."""
    if r is None:
        return None
    return r.get("rerank_score", r.get("reranker_score"))


def _final_prompt_context(events):
    """Chunk ids that made it into the final assembled prompt."""
    prompt = _latest(events, "prompt.assembled")
    if not prompt:
        return []
    return prompt.payload.get("context") or []


def _chunk_status(good, bad):
    """Classify what changed for a chunk present in both runs."""
    if good.get("selected") and not bad.get("selected"):
        return "deselected"
    if not good.get("selected") and bad.get("selected"):
        return "newly_selected"
    if good.get("rank") != bad.get("rank"):
        return "rank_changed"
    if good.get("score") != bad.get("score"):
        return "score_changed"
    return "unchanged"


def _diff_chunks(events_a, events_b):
    """Side-by-side comparison of every retrieved chunk across two runs.

    Returns a list of row dicts, one per chunk that changed (or took part
    in a final-prompt replacement). Each row carries the good/bad values
    for rank, retrieval score, reranker score and selected state, plus a
    status tag and the similarity delta.
    """
    retr_a = _index_retrieval_results(events_a)
    retr_b = _index_retrieval_results(events_b)
    ctx_a = _final_prompt_context(events_a)
    ctx_b = _final_prompt_context(events_b)

    # Same position in the final prompt context, different chunk => replacement.
    replacements = {}  # good chunk id -> bad chunk id
    for i in range(max(len(ctx_a), len(ctx_b))):
        ca = ctx_a[i] if i < len(ctx_a) else None
        cb = ctx_b[i] if i < len(ctx_b) else None
        if ca is not None and cb is not None and ca != cb:
            replacements[ca] = cb
    replaced_by = {v: k for k, v in replacements.items()}  # bad chunk id -> good chunk id

    rows = []
    all_ids = list(dict.fromkeys(list(retr_a.keys()) + list(retr_b.keys()) + ctx_a + ctx_b))
    for cid in all_ids:
        good = retr_a.get(cid)
        bad = retr_b.get(cid)
        if good is None and bad is None:
            continue
        if good is None:
            status = "added"
        elif bad is None:
            status = "removed"
        else:
            status = _chunk_status(good, bad)

        good_score = good.get("score") if good else None
        bad_score = bad.get("score") if bad else None
        delta = None
        if good_score is not None and bad_score is not None:
            delta = round(bad_score - good_score, 4)

        row = {
            "chunk_id": cid,
            "source": (good or bad).get("source", ""),
            "good": {
                "rank": good.get("rank") if good else None,
                "score": good_score,
                "rerank_score": _rerank_score(good),
                "selected": good.get("selected") if good else None,
            },
            "bad": {
                "rank": bad.get("rank") if bad else None,
                "score": bad_score,
                "rerank_score": _rerank_score(bad),
                "selected": bad.get("selected") if bad else None,
            },
            "status": status,
            "similarity_delta": delta,
            "replaced_by": replacements.get(cid),
            "replaces": replaced_by.get(cid),
        }
        rows.append(row)

    # Only surface rows that actually changed or participated in a replacement.
    return [r for r in rows if r["status"] != "unchanged" or r["replaced_by"] or r["replaces"]]


def _index_memory_state(events):
    """Best-effort 'final value per key' view derived from the append-only
    memory.write / memory.update / memory.delete log."""
    state = {}
    for e in events:
        if e.type == "memory.write":
            state[e.payload["key"]] = e.payload.get("value")
        elif e.type == "memory.update":
            state[e.payload["key"]] = e.payload.get("new_value")
        elif e.type == "memory.delete":
            state.pop(e.payload["key"], None)
    return state


# ---------------------------------------------------------------------------
# Causal evidence chains (Phase 7)
# ---------------------------------------------------------------------------
# For a single changed memory/context value we walk the bad run's event log
# and trace it through the pipeline: memory -> retrieved -> selected ->
# inserted into context -> in the final prompt -> reflected in the output.
# Each step is *evidence-labeled* (backed by an actual recorded event); a step
# with no supporting event is marked "not reached". This shows *where* a
# change entered execution and whether it actually reached the final prompt and
# output -- without ever claiming token-level attribution.


def _text_of(value: Any) -> str:
    return "" if value is None else str(value)


def _values_equal(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        if isinstance(a, bool) or isinstance(b, bool):
            return a == b
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def _chain_memory_step(events, key, value):
    """Any memory event for this key that carries this value? Returns a step."""
    for e in events:
        p = e.payload or {}
        if p.get("key") != key:
            continue
        val = p.get("value", p.get("new_value"))
        if _values_equal(val, value):
            op = e.type.replace("memory.", "")
            return {
                "stage": "memory",
                "status": "reached",
                "seq": e.seq,
                "detail": f"memory.{op} set '{key}' to {_text_of(value)!r}",
            }
    return None


def _chain_retrieval_step(events, value):
    """Did this value surface in a retrieval.result? Returns a step or None."""
    for e in events:
        if e.type != "retrieval.result":
            continue
        for r in e.payload.get("results", []):
            if _values_equal(r.get("content") or r.get("id"), value):
                sel = r.get("selected")
                return {
                    "stage": "retrieval",
                    "status": "reached",
                    "seq": e.seq,
                    "detail": (
                        f"surfaced as chunk '{r.get('id') or r.get('content')}'"
                        f" (score {r.get('score')}, rank {r.get('rank')}, "
                        f"selected={sel})"
                    ),
                    "selected": sel,
                }
    return None


def _chain_context_step(events, key, value):
    """Was this value injected as a context.block? Returns a step or None."""
    for e in events:
        if e.type != "context.block":
            continue
        p = e.payload or {}
        if (p.get("key") and _values_equal(p.get("key"), key)) or _values_equal(
            p.get("content"), value
        ):
            return {
                "stage": "context",
                "status": "reached",
                "seq": e.seq,
                "detail": (
                    f"injected as context block '{p.get('key') or p.get('source')}'"
                    f" (order {p.get('order')}, source {p.get('source')})"
                ),
            }
    return None


def _chain_prompt_step(events, key, value):
    """Does the final assembled prompt reference this key/value? Returns a step."""
    prompt = _latest(events, "prompt.assembled")
    if not prompt:
        return None
    p = prompt.payload or {}
    ctx = p.get("context") or []
    if key in ctx:
        return {
            "stage": "final_prompt",
            "status": "reached",
            "seq": prompt.seq,
            "detail": f"chunk '{key}' is in the final prompt context list",
        }
    text = _prompt_to_text(p.get("system"), p.get("messages"))
    if _text_of(value) and _text_of(value).lower() in text.lower():
        return {
            "stage": "final_prompt",
            "status": "reached",
            "seq": prompt.seq,
            "detail": "value appears in the assembled prompt text",
        }
    return None


def _chain_output_step(events, value):
    """Does the final output mention this value? Returns a step."""
    for e in events:
        if e.type != "model.response":
            continue
        text = _text_of((e.payload or {}).get("response"))
        if _text_of(value) and _text_of(value).lower() in text.lower():
            return {
                "stage": "output",
                "status": "reached",
                "seq": e.seq,
                "detail": "final answer repeats this value",
            }
    return None


def build_evidence_chain(events, kind, key, value):
    """Trace one changed memory/context value through the bad run pipeline.

    ``kind`` is ``"memory"`` or ``"context"``. Returns a dict with ``steps``,
    ``broken_at`` (first stage from the entry point on without evidence, or
    None), and a note distinguishing event-level evidence from output
    correlation.

    A *memory* cause starts at the ``memory`` stage; a *context* cause enters
    via retrieval, so the leading ``memory`` stage is marked ``skipped`` (dim)
    rather than "broken" -- it was never part of this cause's path.
    """
    entry_index = 1 if kind == "context" else 0
    stage_fns = (
        ("memory", _chain_memory_step(events, key, value)),
        ("retrieved", _chain_retrieval_step(events, value)),
        ("selected_into_context", _chain_context_step(events, key, value)),
        ("final_prompt", _chain_prompt_step(events, key, value)),
        ("output", _chain_output_step(events, value)),
    )

    steps = []
    for i, (stage, fn_result) in enumerate(stage_fns):
        if i < entry_index:
            steps.append({
                "stage": stage,
                "status": "skipped",
                "seq": None,
                "detail": f"not part of this {kind}-origin cause's path",
            })
        elif fn_result is not None:
            steps.append({**fn_result, "stage": stage})
        else:
            steps.append({
                "stage": stage,
                "status": "not_reached",
                "seq": None,
                "detail": f"no recorded event links this to {stage}",
            })

    path = steps[entry_index:]
    broken_at = next(
        (s["stage"] for s in path if s["status"] == "not_reached"), None
    )
    return {
        "kind": kind,
        "key": key,
        "value": value,
        "steps": steps,
        "broken_at": broken_at,
        "caveat": (
            "Event-level and context-level evidence plus output correlation "
            "only -- true token-level attribution is not available."
        ),
    }




@dataclass
class DiffSection:
    name: str
    changed: bool
    details: list = field(default_factory=list)


@dataclass
class RunDiffResult:
    run_a: str
    run_b: str
    sections: list
    narrative: list
    likely_causes: list
    scored_causes: list = field(default_factory=list)
    evidence_chains: list = field(default_factory=list)

    def to_dict(self):
        return {
            "run_a": self.run_a,
            "run_b": self.run_b,
            "sections": [
                {"name": s.name, "changed": s.changed, "details": s.details} for s in self.sections
            ],
            "narrative": self.narrative,
            "likely_causes": self.likely_causes,
            "scored_causes": self.scored_causes,
            "evidence_chains": self.evidence_chains,
        }


def diff_runs_multi(store: TraceStore, baseline: str, candidates: list[str]) -> dict:
    """Compare a baseline (good) run against multiple candidate (bad) runs.

    Returns a dict with:
      - ``baseline``: the baseline run id
      - ``comparisons``: one ``RunDiffResult.to_dict()`` per candidate
      - ``common_causes``: likely causes that appear in *every* candidate
        comparison (the strongest signal that a single root cause explains
        all the bad runs)
    """
    comparisons = []
    common_causes: list[str] = []
    for candidate in candidates:
        if candidate == baseline:
            continue
        result = diff_runs(store, baseline, candidate)
        comparisons.append(result.to_dict())
        if not common_causes:
            common_causes = list(result.likely_causes)
        else:
            common_causes = [c for c in common_causes if c in result.likely_causes]
    return {
        "baseline": baseline,
        "candidates": [c for c in candidates if c != baseline],
        "comparisons": comparisons,
        "common_causes": common_causes,
    }


def diff_runs(store: TraceStore, run_a: str, run_b: str) -> RunDiffResult:
    """Diff run_a ("good"/baseline) against run_b ("bad"/candidate)."""
    events_a = store.get_events(run_a)
    events_b = store.get_events(run_b)

    sections: list[DiffSection] = []
    narrative: list[str] = []
    likely_causes: list[str] = []

    # -- input -------------------------------------------------------
    input_a = _text(_latest(events_a, "user.input").payload.get("message")) if _latest(events_a, "user.input") else ""
    input_b = _text(_latest(events_b, "user.input").payload.get("message")) if _latest(events_b, "user.input") else ""
    if input_a != input_b:
        sections.append(DiffSection("input", True, [{"good": input_a, "bad": input_b}]))
        narrative.append("The user input itself differed between the two runs.")
    else:
        sections.append(DiffSection("input", False, []))

    # -- retrieval -----------------------------------------------------
    retr_a = _index_retrieval_results(events_a)
    retr_b = _index_retrieval_results(events_b)
    added = [k for k in retr_b if k not in retr_a]
    removed = [k for k in retr_a if k not in retr_b]
    rank_changed = []
    for k in retr_a:
        if k in retr_b:
            ra, rb = retr_a[k].get("rank"), retr_b[k].get("rank")
            if ra is not None and rb is not None and ra != rb:
                rank_changed.append({"item": k, "good_rank": ra, "bad_rank": rb})
    retrieval_changed = bool(added or removed or rank_changed)
    if retrieval_changed:
        sections.append(DiffSection("retrieval", True, [
            {"added_in_bad_run": added, "missing_in_bad_run": removed, "rank_changes": rank_changed}
        ]))
        for item in removed:
            narrative.append(f"Retrieval no longer surfaced '{item}', which the good run relied on.")
        for item in added:
            narrative.append(f"Retrieval surfaced a new/different item in the bad run: '{item}'.")
        for rc in rank_changed:
            narrative.append(
                f"'{rc['item']}' moved from rank #{rc['good_rank']} to rank #{rc['bad_rank']}."
            )
    else:
        sections.append(DiffSection("retrieval", False, []))

    # -- memory chunks (side-by-side chunk diff) --------------------------
    chunk_rows = _diff_chunks(events_a, events_b)
    if chunk_rows:
        sections.append(DiffSection("chunks", True, chunk_rows))
        for row in chunk_rows:
            cid = row["chunk_id"]
            if row["status"] == "added":
                narrative.append(
                    f"Chunk '{cid}' (source: {row['source']}) was newly retrieved in the bad run."
                )
            elif row["status"] == "removed":
                narrative.append(
                    f"Chunk '{cid}' (source: {row['source']}) was retrieved in the good run but is gone in the bad run."
                )
            elif row["status"] == "newly_selected":
                narrative.append(
                    f"Chunk '{cid}' was newly selected for the final prompt in the bad run."
                )
            elif row["status"] == "deselected":
                narrative.append(
                    f"Chunk '{cid}' was selected in the good run but dropped in the bad run."
                )
            elif row["status"] == "rank_changed":
                narrative.append(
                    f"Chunk '{cid}' moved from rank #{row['good']['rank']} to rank #{row['bad']['rank']}."
                )
            elif row["status"] == "score_changed":
                narrative.append(
                    f"Chunk '{cid}' score changed from {row['good']['score']} to {row['bad']['score']} "
                    f"(delta {row['similarity_delta']:+})."
                )
            # A chunk can change rank/score even when its primary status is
            # something else (e.g. newly selected AND moved from #7 to #1).
            if row["status"] not in ("rank_changed", "added", "removed"):
                g_rank, b_rank = row["good"]["rank"], row["bad"]["rank"]
                if g_rank is not None and b_rank is not None and g_rank != b_rank:
                    narrative.append(
                        f"Chunk '{cid}' also moved from rank #{g_rank} to rank #{b_rank}."
                    )
            if row["replaced_by"]:
                narrative.append(
                    f"Chunk '{cid}' was replaced by chunk '{row['replaced_by']}' in the final prompt."
                )
    else:
        sections.append(DiffSection("chunks", False, []))

    # -- context blocks --------------------------------------------------
    ctx_a = _index_context_blocks(events_a)
    ctx_b = _index_context_blocks(events_b)
    ctx_added = [k for k in ctx_b if k not in ctx_a]
    ctx_removed = [k for k in ctx_a if k not in ctx_b]
    ctx_reordered = []
    for k in ctx_a:
        if k in ctx_b and ctx_a[k]["position"] != ctx_b[k]["position"]:
            ctx_reordered.append({
                "key": k, "good_position": ctx_a[k]["position"], "bad_position": ctx_b[k]["position"],
            })
    ctx_changed_value = []
    for k in ctx_a:
        if k in ctx_b and _text(ctx_a[k].get("content")) != _text(ctx_b[k].get("content")):
            ctx_changed_value.append({
                "key": k, "good_content": ctx_a[k].get("content"), "bad_content": ctx_b[k].get("content"),
            })
    context_changed = bool(ctx_added or ctx_removed or ctx_reordered or ctx_changed_value)
    if context_changed:
        sections.append(DiffSection("context", True, [{
            "added_in_bad_run": ctx_added,
            "missing_in_bad_run": ctx_removed,
            "reordered": ctx_reordered,
            "value_changed": ctx_changed_value,
        }]))
        for k in ctx_removed:
            narrative.append(f"Context block '{k}' (present in the good run) was not injected in the bad run.")
        for k in ctx_added:
            narrative.append(f"A new context block '{k}' was injected only in the bad run.")
        for rc in ctx_reordered:
            narrative.append(
                f"Context block '{rc['key']}' moved from position {rc['good_position']} "
                f"to position {rc['bad_position']} in the assembled prompt."
            )
        for cv in ctx_changed_value:
            narrative.append(f"Context block '{cv['key']}' had different content in the bad run.")
    else:
        sections.append(DiffSection("context", False, []))

    # -- prompt --------------------------------------------------------
    prompt_a = _latest(events_a, "prompt.assembled")
    prompt_b = _latest(events_b, "prompt.assembled")
    prompt_changed = False
    if prompt_a and prompt_b:
        sys_a, sys_b = prompt_a.payload.get("system"), prompt_b.payload.get("system")
        msgs_a, msgs_b = prompt_a.payload.get("messages"), prompt_b.payload.get("messages")
        prompt_changed = (sys_a != sys_b) or (msgs_a != msgs_b)
        if prompt_changed:
            # Token-level diff of the flattened prompt so the UI can show
            # exactly which tokens were added/removed/replaced. This is an
            # *estimate* unless exact token counts were recorded.
            text_a = _prompt_to_text(sys_a, msgs_a)
            text_b = _prompt_to_text(sys_b, msgs_b)
            token_diff = _diff_tokens(text_a, text_b)
            recorded_counts = {
                "good": _recorded_token_counts(prompt_a.payload),
                "bad": _recorded_token_counts(prompt_b.payload),
            }
            sections.append(DiffSection("prompt", True, [{
                "good_system": sys_a, "bad_system": sys_b,
                "good_messages": msgs_a, "bad_messages": msgs_b,
                "token_diff": token_diff,
                "token_counts": {
                    "estimate": True,
                    "prompt_tokens_a": token_diff["estimated_counts"]["a_total_tokens"],
                    "prompt_tokens_b": token_diff["estimated_counts"]["b_total_tokens"],
                    "delta": (
                        token_diff["estimated_counts"]["b_total_tokens"]
                        - token_diff["estimated_counts"]["a_total_tokens"]
                    ),
                    "recorded": recorded_counts,
                },
            }]))
            if sys_a != sys_b:
                narrative.append("The system prompt differed between runs.")
            if msgs_a != msgs_b:
                narrative.append("The final assembled messages sent to the model differed between runs.")
            if token_diff["removed_count"] or token_diff["added_count"]:
                narrative.append(
                    f"The prompt changed by {token_diff['removed_count']} removed and "
                    f"{token_diff['added_count']} added token span(s)."
                )
        else:
            sections.append(DiffSection("prompt", False, []))
    else:
        sections.append(DiffSection("prompt", False, []))

    # -- tools -----------------------------------------------------------
    tools_a = [e.payload for e in events_a if e.type in ("tool.call", "tool.result")]
    tools_b = [e.payload for e in events_b if e.type in ("tool.call", "tool.result")]
    tools_changed = tools_a != tools_b
    if tools_changed:
        sections.append(DiffSection("tools", True, [{"good": tools_a, "bad": tools_b}]))
        names_a = {t.get("name") for t in tools_a if "result" in t}
        names_b = {t.get("name") for t in tools_b if "result" in t}
        for name in names_a & names_b:
            ra = next((t["result"] for t in tools_a if t.get("name") == name and "result" in t), None)
            rb = next((t["result"] for t in tools_b if t.get("name") == name and "result" in t), None)
            if ra != rb:
                narrative.append(f"Tool '{name}' returned different data in the bad run.")
    else:
        sections.append(DiffSection("tools", False, []))

    # -- memory ----------------------------------------------------------
    mem_a = _index_memory_state(events_a)
    mem_b = _index_memory_state(events_b)
    mem_diff_keys = [k for k in set(mem_a) | set(mem_b) if mem_a.get(k) != mem_b.get(k)]
    memory_changed = bool(mem_diff_keys)
    if memory_changed:
        sections.append(DiffSection("memory", True, [
            {"key": k, "good_value": mem_a.get(k), "bad_value": mem_b.get(k)} for k in mem_diff_keys
        ]))
        for k in mem_diff_keys:
            narrative.append(f"Memory key '{k}' held a different value in the bad run.")
    else:
        sections.append(DiffSection("memory", False, []))

    # -- output ----------------------------------------------------------
    out_a = _latest(events_a, "model.response")
    out_b = _latest(events_b, "model.response")
    text_a = _text(out_a.payload.get("response")) if out_a else ""
    text_b = _text(out_b.payload.get("response")) if out_b else ""
    output_changed = text_a != text_b
    if output_changed:
        sections.append(DiffSection("output", True, [{"good": text_a, "bad": text_b}]))
        narrative.append("The final answer differed between the two runs.")
    else:
        sections.append(DiffSection("output", False, []))

    # -- heuristic causal linking ------------------------------------
    # If a stale/removed/changed context or memory value shows up verbatim
    # in the bad run's answer, call it out as a likely cause rather than
    # just another line item. Each cause also gets a confidence score
    # (0.0 - 1.0) so the UI can rank them.
    _numeric_token = re.compile(r"\$?\d[\d,.]*%?")

    def _salient_tokens(text: str) -> set:
        return set(_numeric_token.findall(text or ""))

    def _mentions(haystack: str, needle: str) -> bool:
        """True if `needle`'s distinctive content shows up in `haystack`.

        Two ways to match, since real model output rarely repeats context
        verbatim: (1) a reasonably long literal substring, or (2) a shared
        salient numeric/monetary token (e.g. a stale price or percentage),
        which is the most common real-world case of a stale value leaking
        into an answer.
        """
        needle = (needle or "").strip()
        if not needle:
            return False
        if len(needle) > 6 and needle.lower() in (haystack or "").lower():
            return True
        shared = _salient_tokens(needle) & _salient_tokens(haystack)
        return bool(shared)

    def _mention_strength(haystack: str, needle: str) -> float:
        """Confidence that `needle`'s content leaked into `haystack`.

        Returns 1.0 for a verbatim literal match, 0.7 for a shared salient
        numeric token, 0.0 otherwise.
        """
        needle = (needle or "").strip()
        if not needle:
            return 0.0
        if len(needle) > 6 and needle.lower() in (haystack or "").lower():
            return 1.0
        shared = _salient_tokens(needle) & _salient_tokens(haystack)
        return 0.7 if shared else 0.0

    scored_causes: list[dict] = []

    def _add_cause(message: str, confidence: float) -> None:
        likely_causes.append(message)
        scored_causes.append({
            "message": message,
            "confidence": round(confidence, 2),
        })

    if text_b:
        for cv in ctx_changed_value:
            bad_val = _text(cv.get("bad_content"))
            if _mentions(text_b, bad_val) and not _mentions(text_a, bad_val):
                _add_cause(
                    f"The bad run's answer repeats content from context block '{cv['key']}' "
                    f"that differed from the good run -- this is likely the cause.",
                    _mention_strength(text_b, bad_val),
                )
        for k in ctx_added:
            bad_val = _text(ctx_b[k].get("content"))
            if _mentions(text_b, bad_val) and not _mentions(text_a, bad_val):
                _add_cause(
                    f"The bad run's answer repeats content from context block '{k}' "
                    f"(source: {ctx_b[k].get('source')}), which only appeared in the bad run "
                    f"-- this is likely the cause.",
                    _mention_strength(text_b, bad_val),
                )
        for k in ctx_removed:
            good_val = _text(ctx_a[k].get("content"))
            if _mentions(text_a, good_val) and not _mentions(text_b, good_val):
                _add_cause(
                    f"Context block '{k}' (source: {ctx_a[k].get('source')}) grounded the good "
                    f"run's answer but was missing from the bad run's prompt.",
                    _mention_strength(text_a, good_val),
                )
        for k in mem_diff_keys:
            bad_val = _text(mem_b.get(k))
            if _mentions(text_b, bad_val) and not _mentions(text_a, bad_val):
                _add_cause(
                    f"The bad run's answer repeats memory value '{k}' = '{bad_val}', "
                    f"which differed from the good run -- this is likely the cause.",
                    _mention_strength(text_b, bad_val),
                )

    # Sort scored causes by confidence (highest first) so the UI can
    # present the most likely explanation first.
        scored_causes.sort(key=lambda c: c["confidence"], reverse=True)

    # Causal evidence chains (Phase 7): for each changed memory value / context
    # block / retrieved chunk, trace the *bad* run through memory -> retrieved ->
    # selected -> context -> final prompt -> output, with evidence labels.
    # Memory/context cause values come from the diff; chunk chains resolve the
    # chunk's content from the bad run's retrieval log (best-effort).
    evidence_chains = []

    def _content_of(events, chunk_id):
        for e in events:
            if e.type != "retrieval.result":
                continue
            for r in e.payload.get("results", []):
                if _values_equal(r.get("id"), chunk_id):
                    return r.get("content")
        return chunk_id

    for k in mem_diff_keys:
        evidence_chains.append(
            build_evidence_chain(events_b, "memory", k, _text(mem_b.get(k)))
        )
    for cv in ctx_changed_value:
        evidence_chains.append(
            build_evidence_chain(
                events_b, "context", cv.get("key"), _text(cv.get("bad_content"))
            )
        )
    for k in ctx_added:
        evidence_chains.append(
            build_evidence_chain(
                events_b, "context", k, _text(ctx_b[k].get("content"))
            )
        )
    for row in chunk_rows:
        if row["status"] in ("added", "newly_selected", "rank_changed", "score_changed"):
            cid = row["chunk_id"]
            evidence_chains.append(
                build_evidence_chain(events_b, "retrieval", cid, _text(_content_of(events_b, cid)))
            )

    return RunDiffResult(
        run_a=run_a, run_b=run_b, sections=sections,
        narrative=narrative, likely_causes=likely_causes,
        scored_causes=scored_causes, evidence_chains=evidence_chains,
    )
