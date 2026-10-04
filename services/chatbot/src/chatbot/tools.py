from __future__ import annotations

from langchain_core.tools import tool

from chatbot.bigquery import rows_to_tool_text, run_query
from chatbot.schema_catalog import SCHEMA_TEXT
from chatbot.sql_guard import SqlGuardError


@tool
def list_schema() -> str:
    """List the allowed BigQuery tables and columns for retail analysis."""
    return SCHEMA_TEXT


@tool
def run_sql(sql: str) -> str:
    """Run a read-only BigQuery SELECT against allowed thelook_ecommerce tables.

    Use fully-qualified table names. Only SELECT/WITH is allowed.
    """
    try:
        payload = run_query(sql)
    except SqlGuardError as exc:
        return f"SQL rejected: {exc}"
    except Exception as exc:  # noqa: BLE001 - return to agent for repair
        return f"BigQuery error: {exc}"
    return rows_to_tool_text(payload)
