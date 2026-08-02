"""
Best-effort redaction applied before an event is written to disk.

This is not a security boundary -- it's a courtesy so that obvious secrets
(API keys, passwords, tokens) don't end up sitting in a local SQLite file
just because they passed through a prompt or tool call. Keep it simple and
predictable rather than clever.
"""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|password|passwd|token|access[_-]?key|authorization|"
    r"bearer|private[_-]?key|ssn|credit[_-]?card)",
    re.IGNORECASE,
)

# Catches common high-entropy secret shapes inline in strings (e.g. "sk-...").
INLINE_SECRET_PATTERN = re.compile(r"\b(sk|pk|key|token)-[A-Za-z0-9_\-]{16,}\b", re.IGNORECASE)

REDACTED = "[REDACTED]"


def _redact_string(value: str) -> str:
    return INLINE_SECRET_PATTERN.sub(REDACTED, value)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and SENSITIVE_KEY_PATTERN.search(k):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value
