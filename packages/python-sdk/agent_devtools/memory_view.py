"""
Temporal memory view -- answer: "what did the agent actually know at the
moment it made the decision, and has that memory changed since?"

Memory state can change after a run or part-way through one, so a single
"current value" is not enough to debug an agent. This module derives, at read
time, a per-key comparison between:

- the value the agent *observed at decision time* (a ``memory.read``), and
- the *current* value established by the write/update/delete chain.

and labels each key with a status:

- ``consistent``         -- read value matches the current value.
- ``stale_after_run``    -- read value differs from the current value: the run
                            decided from memory that has since changed. This is
                            the classic stale-memory bug.
- ``deleted_after_run``  -- the key the run read was later deleted.
- ``observed_only``      -- we saw a read but no write chain in this run, so
                            the current value is unknown (external seed).
- ``write_only``         -- we know the current value but never saw a read, so
                            no at-decision-time value is recorded.
- ``history_only``       -- only a delete was recorded; no value evidence.

Where the instrumentation recorded it, the optional ``created_at`` /
``updated_at`` / ``deleted_at`` / ``observed_at`` / ``version`` fields on
memory events are surfaced too. When historical (observed) state is not
available we say so explicitly and never invent a value.

Backwards compatible: keys/fields are derived from whatever the trace
recorded; traces without the optional temporal fields simply report
``consistent`` / ``write_only`` with no timestamps.
"""

from __future__ import annotations

from typing import Any, Optional


# Status labels used both by the engine and by the UI.
STALE = "stale_after_run"
CONSISTENT = "consistent"
DELETED = "deleted_after_run"
OBSERVED_ONLY = "observed_only"
WRITE_ONLY = "write_only"
HISTORY_ONLY = "history_only"


def _ts(event_ts: float, payload: dict, field: str) -> Optional[float]:
    """Prefer an explicitly-recorded timestamp, fall back to the event ts."""
    val = payload.get(field)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


class _Entry:
    """Mutable running state for one memory key while we walk the log."""

    __slots__ = ("key", "current", "created_at", "updated_at", "deleted_at",
                 "version", "_ever_written", "_ever_deleted")

    def __init__(self, key: str) -> None:
        self.key = key
        self.current = None          # current value (or None if deleted)
        self.created_at: Optional[float] = None
        self.updated_at: Optional[float] = None
        self.deleted_at: Optional[float] = None
        self.version: Any = None
        self._ever_written = False
        self._ever_deleted = False

    # -- helpers for status determination -------------------------
    @property
    def ever_written(self) -> bool:
        return self._ever_written

    @property
    def ever_deleted(self) -> bool:
        return self._ever_deleted


def _walk_keys(events):
    """Build {key: _Entry} of the current write/update/delete state."""
    keys: dict[str, _Entry] = {}
    for e in events:
        p = e.payload or {}
        k = p.get("key")
        if k is None:
            continue
        entry = keys.setdefault(k, _Entry(k))
        if e.type == "memory.write":
            entry._ever_written = True
            entry.current = p.get("value")
            entry.created_at = _ts(e.ts, p, "created_at")
            entry.updated_at = _ts(e.ts, p, "updated_at")
            entry.version = p.get("version", entry.version)
        elif e.type == "memory.update":
            entry._ever_written = True
            entry.current = p.get("new_value")
            if entry.created_at is None:
                entry.created_at = _ts(e.ts, p, "created_at")
            entry.updated_at = _ts(e.ts, p, "updated_at")
            entry.version = p.get("version", entry.version)
        elif e.type == "memory.delete":
            entry._ever_deleted = True
            entry.current = None
            entry.deleted_at = _ts(e.ts, p, "deleted_at")
    return keys

def _collect_reads(events) -> dict[str, list]:
    """Group memory.read evidence by key (in order)."""
    reads: dict[str, list] = {}
    for e in events:
        if e.type != "memory.read":
            continue
        p = e.payload or {}
        k = p.get("key")
        if k is None:
            continue
        reads.setdefault(k, []).append({
            "value": p.get("value"),
            "observed_at": _ts(e.ts, p, "observed_at"),
            "version": p.get("version"),
            "seq": e.seq,
        })
    return reads


def memory_view(events) -> dict:
    """Derive the temporal memory view for one run's events.

    Returns ``{ "keys": { "<key>": {...} }, "summary": str, "stale": [...] }``.
    """
    keys = _walk_keys(events)
    reads = _collect_reads(events)

    out: dict[str, dict] = {}
    defective = 0

    for key in sorted(set(keys) | set(reads)):
        entry = keys.get(key)
        observed = reads.get(key)
        latest_read = observed[-1] if observed else None

        current = entry.current if entry is not None else None
        historical_available = latest_read is not None
        status: str
        notes: list[str] = []

        if latest_read is not None:
            if entry is not None and entry._ever_deleted and current is None:
                status = DELETED
            elif entry is not None and entry._ever_written and current is not None:
                status = (
                    STALE
                    if _values_differ(latest_read.get("value"), current)
                    else CONSISTENT
                )
            else:
                # Read exists but no write chain in this run -> external seed.
                status = OBSERVED_ONLY
                notes.append(
                    "Current value is not recorded in this run (external seed); "
                    "the observed value may have changed after the run."
                )
        else:
            if entry is not None and entry._ever_written:
                status = WRITE_ONLY
            elif entry is not None and entry._ever_deleted:
                status = HISTORY_ONLY
            else:
                continue  # nothing meaningful recorded for this key

        if status == STALE:
            defective += 1

        observed_out = None
        if latest_read is not None:
            observed_out = {
                "value": latest_read.get("value"),
                "observed_at": latest_read.get("observed_at"),
                "version": latest_read.get("version"),
                "seq": latest_read.get("seq"),
            }

        current_out = None
        if entry is not None and entry._ever_written and entry.current is not None:
            current_out = {
                "value": entry.current,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "version": entry.version,
            }
        elif entry is not None and entry._ever_deleted:
            current_out = {
                "value": None,
                "deleted_at": entry.deleted_at,
            }

        out[key] = {
            "key": key,
            "observed": observed_out,
            "current": current_out,
            "status": status,
            "historical_available": historical_available,
            "notes": notes,
        }

    if defective:
        summary = (
            f"{defective} memory key(s) were read at decision time but have "
            f"since changed -- at least one decision was made from stale memory."
        )
    elif out:
        summary = (
            f"{len(out)} memory key(s) inspected; every observed value still "
            f"matches the current value."
        )
    else:
        summary = "No memory events recorded for the temporal memory view."

    stale_keys = [k for k, v in out.items() if v["status"] == STALE]
    return {"keys": out, "summary": summary, "stale": stale_keys, "count": len(out)}


def _values_differ(a: Any, b: Any) -> bool:
    """Compare two recorded values (handles numeric/string/None gracefully)."""
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    # Best-effort numeric normalization so 29 != 29.0 doesn't false-positive.
    try:
        if isinstance(a, bool) or isinstance(b, bool):
            return a != b
        fa, fb = float(a), float(b)
        return fa != fb
    except (TypeError, ValueError):
        return a != b

