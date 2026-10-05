"""PII sanitization helpers reusable across chat, tools, and later LangSmith."""

from __future__ import annotations

from chatbot.pii import (
    EMAIL_TOKEN,
    PHONE_TOKEN,
    sanitize_pii,
    sanitize_rows,
    sanitize_value,
)

# Hold back enough characters so a late-forming email/phone can still be replaced
# before any prefix is streamed to the client.
DEFAULT_STREAM_HOLDBACK = 320


class PiiStreamSanitizer:
    """Accumulate streamed text and emit only PII-safe prefixes.

    Call :meth:`finalize` at the end of each logical message so the held tail
    is scrubbed and flushed.
    """

    def __init__(self, holdback: int = DEFAULT_STREAM_HOLDBACK) -> None:
        self._raw = ""
        self._emitted_len = 0
        self._holdback = max(0, holdback)

    def push(self, text: str) -> str:
        if not text:
            return ""
        self._raw += text
        return self._emit(finalize=False)

    def finalize(self) -> str:
        delta = self._emit(finalize=True)
        self._raw = ""
        self._emitted_len = 0
        return delta

    def _emit(self, *, finalize: bool) -> str:
        sanitized = sanitize_pii(self._raw)
        if finalize:
            available = sanitized
        else:
            cut = max(0, len(sanitized) - self._holdback)
            available = sanitized[:cut]
        if len(available) < self._emitted_len:
            return ""
        delta = available[self._emitted_len :]
        self._emitted_len = len(available)
        return delta


__all__ = [
    "DEFAULT_STREAM_HOLDBACK",
    "EMAIL_TOKEN",
    "PHONE_TOKEN",
    "PiiStreamSanitizer",
    "sanitize_pii",
    "sanitize_rows",
    "sanitize_value",
]
