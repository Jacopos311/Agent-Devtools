"""Redaction hooks for sensitive data."""

from typing import Dict, Any

SENSITIVE_KEYS = {"api_key", "token", "password", "secret", "authorization"}


def redact_sensitive_keys(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return payload

    result = {}
    for key, value in payload.items():
        if key.lower() in SENSITIVE_KEYS:
            result[key] = "***REDACTED***"
        elif isinstance(value, dict):
            result[key] = redact_sensitive_keys(value)
        elif isinstance(value, list):
            result[key] = [
                redact_sensitive_keys(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result