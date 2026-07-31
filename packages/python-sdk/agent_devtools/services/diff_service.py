"""Diff service for comparing runs."""

import json
from typing import List, Dict
from collections import defaultdict

from ..transport import Transport
from ..schemas import DiffResponse, DiffItem


def _get_events_dict(transport: Transport, run_id: str) -> Dict[str, List[Dict]]:
    """Get events grouped by type for a run."""
    events = transport.get_events(run_id, limit=10000)
    grouped = defaultdict(list)
    for event in events:
        event_type = event["event_type"]
        payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
        grouped[event_type].append({
            "event_type": event_type,
            "payload": payload,
            "timestamp": event["timestamp"]
        })
    return dict(grouped)


def _diff_payloads(payload_a: Dict, payload_b: Dict, path: str = "") -> List[DiffItem]:
    """Recursively diff two payloads."""
    differences = []

    all_keys = set(payload_a.keys()) | set(payload_b.keys())

    for key in all_keys:
        current_path = f"{path}.{key}" if path else key
        val_a = payload_a.get(key)
        val_b = payload_b.get(key)

        if key not in payload_a:
            differences.append(DiffItem(
                path=current_path,
                type="added",
                new_value=val_b
            ))
        elif key not in payload_b:
            differences.append(DiffItem(
                path=current_path,
                type="removed",
                old_value=val_a
            ))
        elif isinstance(val_a, dict) and isinstance(val_b, dict):
            differences.extend(_diff_payloads(val_a, val_b, current_path))
        elif val_a != val_b:
            differences.append(DiffItem(
                path=current_path,
                type="changed",
                old_value=val_a,
                new_value=val_b
            ))

    return differences


def _categorize_diff(diff_item: DiffItem) -> str:
    """Categorize a diff item based on its path or context."""
    path = diff_item.path.lower()
    if "prompt" in path:
        return "prompt"
    elif "context" in path:
        return "context"
    elif "retrieval" in path:
        return "retrieval"
    elif "memory" in path:
        return "memory"
    elif "tool" in path or "call" in path:
        return "tools"
    else:
        return "generic"


def compare_runs(run_a_id: str, run_b_id: str, transport: Transport) -> DiffResponse:
    """Compare two runs and return structured differences."""

    # Verify both runs exist
    run_a = transport.get_run(run_a_id)
    run_b = transport.get_run(run_b_id)
    if not run_a or not run_b:
        raise ValueError("One or both runs not found")

    events_a = _get_events_dict(transport, run_a_id)
    events_b = _get_events_dict(transport, run_b_id)

    all_event_types = set(events_a.keys()) | set(events_b.keys())
    differences_by_category = defaultdict(list)

    for event_type in all_event_types:
        list_a = events_a.get(event_type, [])
        list_b = events_b.get(event_type, [])

        # Compare event by event (assume same order)
        for idx in range(max(len(list_a), len(list_b))):
            if idx >= len(list_a):
                # Event only in B
                diff = DiffItem(
                    path=f"{event_type}[{idx}]",
                    type="added",
                    new_value=list_b[idx]["payload"]
                )
            elif idx >= len(list_b):
                # Event only in A
                diff = DiffItem(
                    path=f"{event_type}[{idx}]",
                    type="removed",
                    old_value=list_a[idx]["payload"]
                )
            else:
                # Compare payloads
                diffs = _diff_payloads(list_a[idx]["payload"], list_b[idx]["payload"], f"{event_type}[{idx}]")
                for d in diffs:
                    category = _categorize_diff(d)
                    differences_by_category[category].append(d)
                continue

            category = _categorize_diff(diff)
            differences_by_category[category].append(diff)

    total_diffs = sum(len(v) for v in differences_by_category.values())

    return DiffResponse(
        run_a_id=run_a_id,
        run_b_id=run_b_id,
        differences_by_category=dict(differences_by_category),
        total_differences=total_diffs
    )