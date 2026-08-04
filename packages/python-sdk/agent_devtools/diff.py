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

from dataclasses import dataclass, field
from typing import Any, Optional

from .store import TraceStore


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


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

    def to_dict(self):
        return {
            "run_a": self.run_a,
            "run_b": self.run_b,
            "sections": [
                {"name": s.name, "changed": s.changed, "details": s.details} for s in self.sections
            ],
            "narrative": self.narrative,
            "likely_causes": self.likely_causes,
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
            sections.append(DiffSection("prompt", True, [{
                "good_system": sys_a, "bad_system": sys_b,
                "good_messages": msgs_a, "bad_messages": msgs_b,
            }]))
            if sys_a != sys_b:
                narrative.append("The system prompt differed between runs.")
            if msgs_a != msgs_b:
                narrative.append("The final assembled messages sent to the model differed between runs.")
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
    # just another line item.
    import re
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

    if text_b:
        for cv in ctx_changed_value:
            bad_val = _text(cv.get("bad_content"))
            if _mentions(text_b, bad_val) and not _mentions(text_a, bad_val):
                likely_causes.append(
                    f"The bad run's answer repeats content from context block '{cv['key']}' "
                    f"that differed from the good run -- this is likely the cause."
                )
        for k in ctx_added:
            bad_val = _text(ctx_b[k].get("content"))
            if _mentions(text_b, bad_val) and not _mentions(text_a, bad_val):
                likely_causes.append(
                    f"The bad run's answer repeats content from context block '{k}' "
                    f"(source: {ctx_b[k].get('source')}), which only appeared in the bad run "
                    f"-- this is likely the cause."
                )
        for k in ctx_removed:
            good_val = _text(ctx_a[k].get("content"))
            if _mentions(text_a, good_val) and not _mentions(text_b, good_val):
                likely_causes.append(
                    f"Context block '{k}' (source: {ctx_a[k].get('source')}) grounded the good "
                    f"run's answer but was missing from the bad run's prompt."
                )
        for k in mem_diff_keys:
            bad_val = _text(mem_b.get(k))
            if _mentions(text_b, bad_val) and not _mentions(text_a, bad_val):
                likely_causes.append(
                    f"The bad run's answer repeats memory value '{k}' = '{bad_val}', "
                    f"which differed from the good run -- this is likely the cause."
                )
    return RunDiffResult(
        run_a=run_a, run_b=run_b, sections=sections,
        narrative=narrative, likely_causes=likely_causes,
    )
