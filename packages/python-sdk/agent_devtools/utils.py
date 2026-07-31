"""Utility functions."""

import uuid
from datetime import datetime


def generate_id() -> str:
    return uuid.uuid4().hex


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat()