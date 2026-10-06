"""Reusable PII scrubbing for email and phone.

Call from chat, tools, traces (e.g. LangSmith), or any other boundary.
Keep detectors here so replacements stay consistent (`EMAIL MASKED`, `PHONE MASKED`).
"""

from __future__ import annotations

import re
from typing import Any

EMAIL_TOKEN = "EMAIL MASKED"
PHONE_TOKEN = "PHONE MASKED"

EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
)

PHONE_RE = re.compile(
    r"(?<!\w)(?:"
    r"\+[\d\-().\s]{8,}\d|"
    r"\d{1,4}[-().\s][\d\-().\s]{5,}\d"
    r")(?!\w)",
)

# Structured row keys whose values are treated as PII even without a regex hit.
_PII_KEY_RE = re.compile(
    r"(^|_)(e[_-]?mail|phone|phone[_-]?number|mobile|tel|telephone)(_|$)",
    re.IGNORECASE,
)


def sanitize_pii(text: str) -> str:
    """Replace email and phone patterns in free text."""
    if not text:
        return text
    cleaned = EMAIL_RE.sub(EMAIL_TOKEN, text)
    cleaned = PHONE_RE.sub(PHONE_TOKEN, cleaned)
    return cleaned


def is_pii_field_name(name: str) -> bool:
    return bool(_PII_KEY_RE.search(name))


def sanitize_value(value: Any) -> Any:
    """Recursively sanitize strings and known PII fields in nested structures."""
    if isinstance(value, str):
        return sanitize_pii(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if item is None or item == "":
                out[key] = item
            elif is_pii_field_name(str(key)):
                out[key] = _token_for_field(str(key))
            else:
                out[key] = sanitize_value(item)
        return out
    return value


def sanitize_rows(payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a BigQuery-style payload (`rows` list of dicts + metadata)."""
    return sanitize_value(payload)


def _token_for_field(name: str) -> str:
    lowered = name.lower()
    if "mail" in lowered:
        return EMAIL_TOKEN
    return PHONE_TOKEN
