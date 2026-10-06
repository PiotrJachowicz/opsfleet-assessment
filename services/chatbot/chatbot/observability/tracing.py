"""LangSmith tracing bootstrap with PII-safe input/output scrubbing."""

from __future__ import annotations

import logging
from typing import Any

from chatbot.config import Settings
from chatbot.pii import sanitize_value

logger = logging.getLogger(__name__)


def _scrub_mapping(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    scrubbed = sanitize_value(payload)
    return scrubbed if isinstance(scrubbed, dict) else {"value": scrubbed}


def configure_langsmith(settings: Settings) -> None:
    """Enable LangSmith only when tracing is on and an API key is present.

    Chat and tools keep working without LangSmith — missing keys simply mean
    no traces are gathered. Failures during setup are logged and ignored.
    """
    try:
        from langsmith import Client, configure
    except Exception:  # noqa: BLE001 - optional observability path
        logger.debug("langsmith package unavailable; tracing skipped", exc_info=True)
        return

    enabled = bool(settings.langsmith_tracing and settings.langsmith_api_key)
    if not enabled:
        if settings.langsmith_tracing and not settings.langsmith_api_key:
            logger.warning(
                "LANGSMITH_TRACING is true but LANGSMITH_API_KEY is empty; "
                "tracing stays off"
            )
        try:
            configure(enabled=False)
        except Exception:  # noqa: BLE001
            logger.debug("could not disable LangSmith tracing", exc_info=True)
        return

    try:
        client = Client(
            api_key=settings.langsmith_api_key,
            api_url=settings.langsmith_endpoint or None,
            hide_inputs=_scrub_mapping,
            hide_outputs=_scrub_mapping,
        )
        configure(
            client=client,
            enabled=True,
            project_name=settings.langsmith_project,
        )
        logger.info(
            "LangSmith tracing enabled (project=%s)",
            settings.langsmith_project,
        )
    except Exception:  # noqa: BLE001 - never block the chat path
        logger.exception("LangSmith setup failed; continuing without tracing")
        try:
            configure(enabled=False)
        except Exception:  # noqa: BLE001
            pass
