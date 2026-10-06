"""Prometheus application metrics (separate from business logic).

Highest-value agent metrics for dashboards/alerts. LangSmith remains the
deep-dive trace store; these counters/histograms answer "is it failing / how
often / how slow" without cluttering call sites.
"""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

# Dedicated registry so tests can isolate and the /metrics handler stays explicit.
REGISTRY = CollectorRegistry()

CHAT_TURNS = Counter(
    "chatbot_chat_turns_total",
    "Chat turns completed, labeled by terminal status",
    ["status"],
    registry=REGISTRY,
)
CHAT_TURN_DURATION = Histogram(
    "chatbot_chat_turn_duration_seconds",
    "End-to-end chat turn duration in seconds",
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    registry=REGISTRY,
)
TOOL_CALLS = Counter(
    "chatbot_tool_calls_total",
    "Agent tool invocations by tool name and outcome",
    ["tool", "status"],
    registry=REGISTRY,
)
BQ_QUERIES = Counter(
    "chatbot_bq_queries_total",
    "BigQuery run_sql outcomes",
    ["outcome"],
    registry=REGISTRY,
)
MODEL_RETRIES = Counter(
    "chatbot_model_retries_total",
    "Gemini model retry attempts and exhausted retries",
    ["result"],
    registry=REGISTRY,
)
REPORT_DELETES = Counter(
    "chatbot_report_deletes_total",
    "Saved-report deletion lifecycle events",
    ["outcome"],
    registry=REGISTRY,
)
AUTH_FAILURES = Counter(
    "chatbot_auth_failures_total",
    "Chat auth failures (invalid/missing JWT)",
    registry=REGISTRY,
)


def record_auth_failure() -> None:
    AUTH_FAILURES.inc()


def record_tool_call(tool: str, status: str) -> None:
    TOOL_CALLS.labels(tool=tool or "tool", status=status).inc()


def record_tool_result(tool: str, output: Any) -> None:
    """Classify a tool end payload as ok vs error for failure-rate dashboards."""
    text = output if isinstance(output, str) else str(output or "")
    head = text.lstrip()[:80].lower()
    if head.startswith("status: sql_rejected") or head.startswith(
        "status: bigquery_error"
    ):
        record_tool_call(tool, "error")
        return
    if head.startswith("failed to"):
        record_tool_call(tool, "error")
        return
    record_tool_call(tool, "ok")


def record_bq_outcome(outcome: str) -> None:
    BQ_QUERIES.labels(outcome=outcome).inc()


def record_model_retry(result: str) -> None:
    """result: retry | exhausted"""
    MODEL_RETRIES.labels(result=result).inc()


def record_report_delete(outcome: str) -> None:
    """outcome: proposed | confirmed | cancelled | error"""
    REPORT_DELETES.labels(outcome=outcome).inc()


class ChatTurnTimer:
    """Time a chat turn and record status + latency in ``finish()``."""

    def __init__(self) -> None:
        self._started = time.perf_counter()
        self.status = "ok"
        self._finished = False

    def mark(self, status: str) -> None:
        self.status = status

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        duration = time.perf_counter() - self._started
        CHAT_TURNS.labels(status=self.status).inc()
        CHAT_TURN_DURATION.observe(duration)


def metrics_response(_: Request | None = None) -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
