from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from google.genai.errors import APIError
from langchain.agents.middleware import ModelRetryMiddleware
from langchain.agents.middleware._retry import calculate_delay, should_retry_exception
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.exceptions import ModelError
from langgraph.errors import GraphBubbleUp

from chatbot.config import Settings
from chatbot.middleware.metrics import record_model_retry

logger = logging.getLogger(__name__)

_RETRY_AFTER_RE = re.compile(
    r"(?:retry\s+in|retryDelay['\"]?\s*:\s*['\"]?)\s*(\d+(?:\.\d+)?)\s*s",
    re.IGNORECASE,
)


def should_retry_gemini(exc: Exception) -> bool:
    """Retry transient Gemini / transport failures, including 429 and 503."""
    if isinstance(exc, ModelError):
        return bool(exc.is_retryable)

    if isinstance(exc, APIError):
        code = getattr(exc, "code", None)
        if code in {408, 429, 500, 502, 503, 504}:
            return True

    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "429",
            "503",
            "unavailable",
            "resource_exhausted",
            "high demand",
            "rate limit",
            "quota",
            "timeout",
            "temporarily",
        )
    )


def suggested_retry_delay_seconds(exc: Exception) -> float | None:
    match = _RETRY_AFTER_RE.search(str(exc))
    if not match:
        return None
    return float(match.group(1))


class GeminiModelRetryMiddleware(ModelRetryMiddleware):
    """Model retries with exponential backoff, honoring API retryDelay when present."""

    def _delay_for_attempt(self, attempt: int, exc: Exception) -> float:
        suggested = suggested_retry_delay_seconds(exc)
        if suggested is not None:
            return min(max(suggested, self.initial_delay), self.max_delay)
        return calculate_delay(
            attempt,
            backoff_factor=self.backoff_factor,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            jitter=self.jitter,
        )

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        for attempt in range(self.max_retries + 1):
            try:
                return handler(request)
            except GraphBubbleUp:
                raise
            except Exception as exc:
                if not should_retry_exception(exc, self.retry_on):
                    raise
                if attempt >= self.max_retries:
                    record_model_retry("exhausted")
                    return self._handle_failure(exc, attempt + 1)

                record_model_retry("retry")
                delay = self._delay_for_attempt(attempt, exc)
                logger.warning(
                    "Gemini model call failed (%s); retry %s/%s in %.1fs",
                    type(exc).__name__,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                if delay > 0:
                    time.sleep(delay)

        raise RuntimeError("Gemini retry loop completed without returning")

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        for attempt in range(self.max_retries + 1):
            try:
                return await handler(request)
            except GraphBubbleUp:
                raise
            except Exception as exc:
                if not should_retry_exception(exc, self.retry_on):
                    raise
                if attempt >= self.max_retries:
                    record_model_retry("exhausted")
                    return self._handle_failure(exc, attempt + 1)

                record_model_retry("retry")
                delay = self._delay_for_attempt(attempt, exc)
                logger.warning(
                    "Gemini model call failed (%s); retry %s/%s in %.1fs",
                    type(exc).__name__,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                if delay > 0:
                    await asyncio.sleep(delay)

        raise RuntimeError("Gemini retry loop completed without returning")


def build_model_retry_middleware(settings: Settings) -> GeminiModelRetryMiddleware:
    return GeminiModelRetryMiddleware(
        max_retries=settings.gemini_max_retries,
        retry_on=should_retry_gemini,
        on_failure="error",
        backoff_factor=settings.gemini_retry_backoff,
        initial_delay=settings.gemini_retry_initial_delay,
        max_delay=settings.gemini_retry_max_delay,
        jitter=True,
    )
