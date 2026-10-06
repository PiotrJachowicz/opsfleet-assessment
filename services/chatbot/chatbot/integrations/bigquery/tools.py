from __future__ import annotations

import logging

from langchain_core.tools import tool

from chatbot.auth import AuthContext, get_auth_context
from chatbot.config import get_settings
from chatbot.integrations.bigquery.client import rows_to_tool_text, run_query
from chatbot.integrations.bigquery.empty_result import (
    format_empty_result,
    note_empty_result,
)
from chatbot.integrations.bigquery.schema_catalog import SCHEMA_TEXT
from chatbot.integrations.bigquery.sql_guard import SqlGuardError
from chatbot.middleware.metrics import record_bq_outcome
from chatbot.middleware.pii import sanitize_pii

logger = logging.getLogger(__name__)


def _schema_for_auth(auth: AuthContext | None) -> str:
    if auth is None or auth.is_admin:
        return SCHEMA_TEXT
    brands = ", ".join(auth.allowed_brands)
    return (
        SCHEMA_TEXT
        + "\n\nAccess note: this user may only analyze brands: "
        + brands
        + ". The service enforces this in SQL automatically."
    )


@tool
def list_schema() -> str:
    """List the allowed BigQuery tables and columns for retail analysis."""
    return _schema_for_auth(get_auth_context())


def execute_run_sql(sql: str) -> str:
    """Execute guarded BigQuery SQL and format empty/error repair payloads."""
    try:
        payload = run_query(sql)
    except SqlGuardError as exc:
        record_bq_outcome("sql_rejected")
        return sanitize_pii(
            "status: sql_rejected\n"
            "repair_required: true\n"
            f"detail: {exc}\n"
            "guidance: Fix the SQL (read-only SELECT/WITH, allowed tables, "
            "fully-qualified names) and call run_sql again."
        )
    except Exception as exc:  # noqa: BLE001 - return to agent for repair
        record_bq_outcome("bq_error")
        return sanitize_pii(
            "status: bigquery_error\n"
            "repair_required: true\n"
            f"detail: {exc}\n"
            "guidance: Repair syntax/filters and retry run_sql. Do not invent "
            "metrics. If the error persists, explain the failure to the user."
        )

    if int(payload.get("row_count") or 0) == 0:
        settings = get_settings()
        attempt = note_empty_result()
        max_attempts = max(1, settings.bq_empty_repair_attempts)
        logger.info(
            "bigquery empty result attempt=%s/%s",
            attempt,
            max_attempts,
        )
        record_bq_outcome(
            "empty_exhausted" if attempt >= max_attempts else "empty"
        )
        return sanitize_pii(
            format_empty_result(
                attempt=attempt,
                max_attempts=max_attempts,
                sql=sql,
            )
        )

    record_bq_outcome("ok")
    return rows_to_tool_text(payload)


@tool
def run_sql(sql: str) -> str:
    """Run a read-only BigQuery SELECT against allowed thelook_ecommerce tables.

    Use fully-qualified table names. Only SELECT/WITH is allowed.
    Empty results return a structured repair directive (bounded per turn).
    """
    return execute_run_sql(sql)
