"""
Scope / isolation debugging -- detect memory & context leakage across
boundaries (cross-tenant, cross-organization, cross-user, etc.).

Scope metadata is entirely optional. When a run records an *expected* scope
and a retrieved/injected piece of evidence records its own *actual* scope, we
can prove (not guess) when the two disagree -- e.g. a memory chunk tagged
``tenant_B`` being pulled into a run that expects ``tenant_A``.

The purpose is to catch the classic isolation bug: an agent answering from a
neighbor tenant's memory. We only ever report a mismatch when both the
expected and the actual scope actually contain the field being compared, and
those values differ. Nothing is fabricated by this module.

Expected scope can come from either (a) run metadata (``metadata["scope"]``),
or (b) a ``scope`` dict recorded on an event. Either way it stays optional.
"""

from __future__ import annotations

from typing import Any, Optional

# The scope dimensions we understand. Order defines display priority.
SCOPE_FIELDS = [
    "tenant_id",
    "organization_id",
    "team_id",
    "session_id",
    "user_id",
    "agent_id",
]


def _extract_scope(payload: dict) -> Optional[dict]:
    """Pull a scope dict out of an event payload.

    Accepts either a nested ``payload["scope"]`` dict or a flat set of the
    known scope fields directly on the payload.
    """
    if not payload:
        return None
    nested = payload.get("scope")
    if isinstance(nested, dict) and nested:
        return dict(nested)
    flat = {f: payload[f] for f in SCOPE_FIELDS if payload.get(f) is not None}
    return flat or None


def _describe(scope: dict) -> str:
    """Human-readable one-line description of a scope dict."""
    parts = []
    for f in SCOPE_FIELDS:
        if scope.get(f) is not None:
            parts.append(f"{f}={scope[f]}")
    return ", ".join(parts) if parts else "(unknown scope)"


def scope_from_metadata(metadata: Optional[dict]) -> Optional[dict]:
    """Extract the expected scope from run metadata, if recorded."""
    if not metadata:
        return None
    scope = metadata.get("scope")
    if isinstance(scope, dict) and scope:
        return dict(scope)
    flat = {f: metadata[f] for f in SCOPE_FIELDS if metadata.get(f) is not None}
    return flat or None


def detect_scope_mismatches(events, expected_scope: Optional[dict] = None,
                            run_metadata: Optional[dict] = None) -> list:
    """Return a list of cross-scope evidence mismatches for a run.

    Each mismatch is only reported when the recorded evidence actually proves
    it: both the expected and the actual scope contain a given field, and the
    values differ. Returns a list of dicts::

        {
            "kind": "memory.read" | "context.block" | "retrieval.result" | ...,
            "key": "...",            # memory key / context key / chunk id
            "field": "tenant_id",
            "expected": "A",
            "actual": "B",
            "expected_scope": {...},
            "actual_scope": {...},
            "message": "Cross-scope memory: expected tenant_id=A, got tenant_id=B",
        }
    """
    expected = expected_scope or scope_from_metadata(run_metadata)
    if not expected:
        return []

    mismatches = []
    # Event types whose payload may carry scope.
    interesting = ("memory.read", "memory.write", "memory.update",
                   "memory.delete", "context.block", "retrieval.result",
                   "state.snapshot")
    for e in events:
        p = e.payload or {}
        actual = _extract_scope(p)
        # A retrieval.result carries scope per-chunk, not on the wrapper.
        if e.type == "retrieval.result" and not actual:
            for r in p.get("results", []):
                chunk_scope = _extract_scope(r)
                if not chunk_scope:
                    continue
                mm = _compare(expected, chunk_scope, e.type,
                              r.get("id") or r.get("content") or "?")
                if mm:
                    mismatches.append(mm)
            continue
        if not actual:
            continue
        key = p.get("key") or p.get("id") or p.get("content") or str(e.seq)
        mm = _compare(expected, actual, e.type, key)
        if mm:
            mismatches.append(mm)
    return mismatches


def _compare(expected: dict, actual: dict, kind: str, key: str) -> Optional[dict]:
    """Return a mismatch dict if any shared scope field differs, else None."""
    for f in SCOPE_FIELDS:
        ev, av = expected.get(f), actual.get(f)
        if ev is None or av is None:
            continue
        # Normalize numeric-like values so 1 != "1" doesn't false-positive.
        if str(ev) != str(av):
            return {
                "kind": kind,
                "key": key,
                "field": f,
                "expected": ev,
                "actual": av,
                "expected_scope": dict(expected),
                "actual_scope": dict(actual),
                "message": (
                    f"Cross-scope {kind.replace('.', ' ')}: expected "
                    f"{f}={ev} but the evidence is tagged {f}={av}. "
                    f"({_describe(actual)})"
                ),
            }
    return None
