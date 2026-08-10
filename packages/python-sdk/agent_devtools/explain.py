"""
Retrieval Explanation -- turn raw retrieval numbers into human-readable
explanations of why each candidate was selected or rejected.

The goal is to explain retrieval decisions instead of only displaying
numbers. For every retrieved memory we surface the original query, the
rewritten query (if any), the filters applied, the embedding model, the
similarity score, the reranker score, the threshold, whether the item was
selected or rejected, and a plain-language reason.

Example output:

    "Selected because similarity score 0.91 exceeded the threshold 0.80."
    "Rejected because similarity score 0.52 was below the threshold 0.80."
    "This chunk was excluded because metadata filters removed it."
    "Rejected because reranker score 0.30 was below the reranker threshold 0.50."
"""

from __future__ import annotations

from typing import Any, Optional


def _num(value: Any) -> Optional[float]:
    """Coerce a value to float, or None if it isn't numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Optional[float], ndigits: int = 2) -> str:
    """Format a number for display, or '-' if None."""
    if value is None:
        return "-"
    return f"{value:.{ndigits}f}"


def _rerank_score(result: dict) -> Optional[float]:
    """Reranker score if the result carries one (either key name)."""
    return _num(result.get("rerank_score", result.get("reranker_score")))


def _threshold(result: dict, query_meta: dict) -> Optional[float]:
    """Per-result threshold, falling back to the query-level threshold."""
    return _num(result.get("threshold", query_meta.get("threshold")))


def _rerank_threshold(result: dict, query_meta: dict) -> Optional[float]:
    """Per-result reranker threshold, falling back to query-level."""
    return _num(result.get("rerank_threshold", query_meta.get("rerank_threshold")))


# Structured retrieval outcomes (Phase 3). These are explicit facts the
# instrumentation can record -- never inferred when they weren't recorded.
OUTCOME_SELECTED = "selected"
OUTCOME_THRESHOLD = "rejected_threshold"        # similarity threshold
OUTCOME_RERANKER = "rejected_reranker"          # reranker score threshold
OUTCOME_FILTER = "rejected_filter"              # metadata filter
OUTCOME_PERMISSION = "rejected_permission"      # access / permission denial
OUTCOME_NO_MATCH = "no_match"                   # nothing matched the query
OUTCOME_REASON = "rejected_reason"              # caller-supplied human reason
OUTCOME_UNKNOWN = "unknown"

VALID_OUTCOMES = {
    OUTCOME_SELECTED, OUTCOME_THRESHOLD, OUTCOME_RERANKER, OUTCOME_FILTER,
    OUTCOME_PERMISSION, OUTCOME_NO_MATCH, OUTCOME_REASON, OUTCOME_UNKNOWN,
}

# Aliases callers may use to record an explicit permission denial.
_DENIAL_ALIASES = {"denied", "access_denied", "forbidden", "permission_denied"}


def classify_outcome(result: dict, query_meta: Optional[dict] = None) -> str:
    """Classify a retrieval result into a structured outcome.

    Priority is: an *explicitly recorded* outcome (or denial) wins; otherwise
    we fall back to the same heuristics ``explain_result`` uses. This keeps
    existing traces producing the same classifications while allowing adapters
    to record denial facts directly.
    """
    query_meta = query_meta or {}
    outcome = result.get("outcome")
    if outcome in VALID_OUTCOMES:
        return outcome
    if result.get("denied") is True or outcome in _DENIAL_ALIASES:
        return OUTCOME_PERMISSION
    if result.get("no_match") is True:
        return OUTCOME_NO_MATCH

    filtered = result.get("filtered")
    selected = result.get("selected")
    if filtered:
        return OUTCOME_FILTER
    if selected is True:
        return OUTCOME_SELECTED

    score = _num(result.get("score"))
    threshold = _threshold(result, query_meta)
    if score is not None and threshold is not None and score < threshold:
        return OUTCOME_THRESHOLD
    rerank = _rerank_score(result)
    rerank_thr = _rerank_threshold(result, query_meta)
    if rerank is not None and rerank_thr is not None and rerank < rerank_thr:
        return OUTCOME_RERANKER
    if result.get("reason"):
        return OUTCOME_REASON
    # Recorded as selected=False with no other signal.
    if selected is False:
        return OUTCOME_REASON
    return OUTCOME_UNKNOWN


def _explicit_denial_reason(result: dict) -> Optional[str]:
    """A recorded denial message, if the caller supplied one.

    We never invent a denial reason -- we only surface what was recorded.
    """
    denial_reason = result.get("denial_reason")
    if isinstance(denial_reason, str) and denial_reason.strip():
        return denial_reason.strip()
    reason = result.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return None

def explain_result(result: dict, query_meta: Optional[dict] = None) -> str:
    """Generate a human-readable explanation for a single retrieval result.

    The decision logic is checked in priority order:

    0. Explicitly recorded denial / outcome (never inferred).
    1. Explicitly filtered out by metadata filters.
    2. Selected (with the reasons that led to selection -- including
       cases where the reranker overrode a below-threshold similarity score).
    3. Below the similarity threshold.
    4. Below the reranker threshold.
    5. User-provided ``reason`` field (fallback).
    6. Generic rejection fallback.
    """
    query_meta = query_meta or {}
    score = _num(result.get("score"))
    threshold = _threshold(result, query_meta)
    rerank = _rerank_score(result)
    rerank_thr = _rerank_threshold(result, query_meta)
    selected = result.get("selected")
    filtered = result.get("filtered")
    reason = result.get("reason")

    # 0. Explicitly recorded denial -- only surfaced when the instrumentation
    #    actually recorded it; the reason text is never invented.
    if result.get("denied") is True or result.get("outcome") in _DENIAL_ALIASES:
        denial = _explicit_denial_reason(result)
        return f"Denied: {denial}" if denial else "Denied (access / permission)."
    if result.get("no_match") is True or result.get("outcome") == OUTCOME_NO_MATCH:
        return "No match -- nothing in the index satisfied the query."


    # 1. Explicitly filtered out by metadata filters.
    if filtered:
        return "This chunk was excluded because metadata filters removed it."

    # 2. Selected.
    if selected:
        parts = []
        below_sim = score is not None and threshold is not None and score < threshold
        if score is not None and threshold is not None and score >= threshold:
            parts.append(
                f"similarity score {_fmt(score)} exceeded the threshold {_fmt(threshold)}"
            )
        elif score is not None:
            parts.append(f"similarity score {_fmt(score)}")

        if rerank is not None:
            if rerank_thr is not None and rerank >= rerank_thr:
                parts.append(
                    f"reranker score {_fmt(rerank)} passed the reranker threshold {_fmt(rerank_thr)}"
                )
            else:
                parts.append(f"reranker score {_fmt(rerank)}")

        if below_sim and rerank is not None and rerank_thr is not None and rerank >= rerank_thr:
            reason = (
                f"Selected despite similarity score {_fmt(score)} being below the threshold "
                f"{_fmt(threshold)} because the reranker score {_fmt(rerank)} passed the "
                f"reranker threshold {_fmt(rerank_thr)}."
            )
            return reason
        if below_sim:
            reason = (
                f"Selected despite similarity score {_fmt(score)} being below the threshold "
                f"{_fmt(threshold)}."
            )
            return reason
        if parts:
            return f"Selected because {' and '.join(parts)}."
        return "Selected for the final prompt."

    # 3. Below the similarity threshold.
    if score is not None and threshold is not None and score < threshold:
        return (
            f"Rejected because similarity score {_fmt(score)} was below "
            f"the threshold {_fmt(threshold)}."
        )

    # 4. Below the reranker threshold.
    if rerank is not None and rerank_thr is not None and rerank < rerank_thr:
        return (
            f"Rejected because reranker score {_fmt(rerank)} was below "
            f"the reranker threshold {_fmt(rerank_thr)}."
        )

    # 5. User-provided reason.
    if reason:
        return reason

    # 6. Fallback.
    return "Rejected because it did not meet the selection criteria."


def _summary(explained: list, query_meta: dict) -> str:
    """Generate a bottom-level human-readable summary of the retrieval
    decision for one query.

    Produces sentences like:

        "The newer memory ranked lower because similarity dropped from
         0.92 to 0.81."

        "This chunk was excluded because metadata filters removed it."

        "2 of 3 candidates were selected; 1 was rejected for falling
         below the similarity threshold 0.80."
    """
    if not explained:
        return "No candidates were returned for this query."

    selected = [r for r in explained if r.get("selected") is True]
    rejected = [r for r in explained if r.get("selected") is False]
    filtered = [r for r in explained if r.get("filtered")]

    parts = []

    # 1. Filtered-out callout.
    for r in filtered:
        parts.append(
            f"Chunk '{r.get('id') or r.get('content') or '?'}' was excluded "
            f"because metadata filters removed it."
        )

    # 2. Rank/score comparisons between selected and rejected candidates.
    #    If a selected candidate outranks a rejected one with a higher
    #    similarity score, that's the interesting story.
    for sel in selected:
        sel_score = _num(sel.get("score"))
        for rej in rejected:
            rej_score = _num(rej.get("score"))
            if sel_score is not None and rej_score is not None and rej_score > sel_score:
                parts.append(
                    f"'{rej.get('id') or rej.get('content') or '?'}' ranked lower "
                    f"despite a higher similarity score ({_fmt(rej_score)} vs {_fmt(sel_score)})."
                )

    # 3. Similarity drop between the top-ranked and next-ranked candidate.
    ranked = sorted(
        [r for r in explained if r.get("rank") is not None],
        key=lambda r: r["rank"],
    )
    if len(ranked) >= 2:
        top, second = ranked[0], ranked[1]
        top_score = _num(top.get("score"))
        second_score = _num(second.get("score"))
        if top_score is not None and second_score is not None and second_score < top_score:
            parts.append(
                f"The next candidate ranked lower because similarity dropped "
                f"from {_fmt(top_score)} to {_fmt(second_score)}."
            )

    # 4. Threshold-based rejection count.
    threshold = _num(query_meta.get("threshold"))
    below_threshold = [
        r for r in rejected
        if _num(r.get("score")) is not None and threshold is not None
        and _num(r.get("score")) < threshold
    ]
    if below_threshold and not filtered:
        parts.append(
            f"{len(below_threshold)} candidate(s) were rejected for falling "
            f"below the similarity threshold {_fmt(threshold)}."
        )

    # 5. Fallback: simple selection count.
    if not parts:
        if selected and not rejected:
            parts.append(f"All {len(selected)} candidate(s) were selected.")
        elif rejected and not selected:
            parts.append(f"All {len(rejected)} candidate(s) were rejected.")
        else:
            parts.append(
                f"{len(selected)} of {len(explained)} candidate(s) were selected; "
                f"{len(rejected)} were rejected."
            )

    return " ".join(parts)


def explain_retrieval(events) -> list:
    """Pair ``retrieval.query`` and ``retrieval.result`` events and produce
    structured explanations for each result.

    Returns a list of dicts, one per retrieval call::

        {
            "query": "...",
            "rewritten_query": "...",
            "filters": {...},
            "embedding_model": "...",
            "threshold": 0.8,
            "rerank_threshold": 0.5,
            "summary": "The next candidate ranked lower because similarity dropped from 0.91 to 0.52.",
            "results": [
                {
                    "id": "...",
                    "content": "...",
                    "source": "memory",
                    "score": 0.91,
                    "rerank_score": 0.85,
                    "rank": 1,
                    "selected": true,
                    "threshold": 0.8,
                    "reason": "Selected because similarity score 0.91 exceeded the threshold 0.80.",
                },
                ...
            ]
        }
    """
    queries = [e.payload for e in events if e.type == "retrieval.query"]
    results = [e.payload for e in events if e.type == "retrieval.result"]

    out = []
    for i, res in enumerate(results):
        q = queries[i] if i < len(queries) else {}
        query_meta = {
            "threshold": q.get("threshold"),
            "rerank_threshold": q.get("rerank_threshold"),
        }
        explained = []
        for r in res.get("results", []):
            explained.append({
                "id": r.get("id"),
                "content": r.get("content"),
                "source": r.get("source"),
                "score": r.get("score"),
                "rerank_score": _rerank_score(r),
                "rank": r.get("rank"),
                "selected": r.get("selected"),
                "filtered": r.get("filtered"),
                "denied": r.get("denied"),
                "denial_reason": r.get("denial_reason"),
                "outcome": classify_outcome(r, query_meta),
                "threshold": _threshold(r, query_meta),
                "reason": explain_result(r, query_meta),
            })
        out.append({
            "query": q.get("query", res.get("query")),
            "rewritten_query": q.get("rewritten_query"),
            "filters": q.get("filters"),
            "embedding_model": q.get("embedding_model"),
            "threshold": q.get("threshold"),
            "rerank_threshold": q.get("rerank_threshold"),
            "summary": _summary(explained, query_meta),
            "results": explained,
        })
    return out
