from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from google.cloud import bigquery
from google.oauth2 import service_account

from chatbot.config import Settings, get_settings
from chatbot.sql_guard import validate_readonly_sql


@lru_cache
def get_bq_client() -> bigquery.Client:
    settings = get_settings()
    if settings.google_application_credentials:
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_application_credentials
        )
        return bigquery.Client(project=settings.gcp_project, credentials=credentials)
    return bigquery.Client(project=settings.gcp_project)


def run_query(sql: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    safe_sql = validate_readonly_sql(sql)
    client = get_bq_client()

    job_config = bigquery.QueryJobConfig(
        dry_run=False,
        use_query_cache=True,
        maximum_bytes_billed=settings.bq_max_bytes_billed,
    )
    job = client.query(safe_sql, job_config=job_config)
    result = job.result(timeout=settings.bq_timeout_seconds)

    rows: list[dict[str, Any]] = []
    for i, row in enumerate(result):
        if i >= settings.bq_max_rows:
            break
        rows.append(dict(row.items()))

    return {
        "row_count": len(rows),
        "truncated": len(rows) >= settings.bq_max_rows,
        "bytes_billed": getattr(job, "total_bytes_billed", None),
        "rows": rows,
    }


def rows_to_tool_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str, indent=2)[:20_000]
