from __future__ import annotations

from langchain_core.tools import tool

from chatbot.auth import AuthContext, get_auth_context
from chatbot.integrations.bigquery.client import rows_to_tool_text, run_query
from chatbot.integrations.bigquery.schema_catalog import SCHEMA_TEXT
from chatbot.integrations.bigquery.sql_guard import SqlGuardError
from chatbot.middleware.pii import sanitize_pii


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


@tool
def run_sql(sql: str) -> str:
    """Run a read-only BigQuery SELECT against allowed thelook_ecommerce tables.

    Use fully-qualified table names. Only SELECT/WITH is allowed.
    """
    try:
        payload = run_query(sql)
    except SqlGuardError as exc:
        return sanitize_pii(f"SQL rejected: {exc}")
    except Exception as exc:  # noqa: BLE001 - return to agent for repair
        return sanitize_pii(f"BigQuery error: {exc}")
    return rows_to_tool_text(payload)
