from unittest.mock import patch

from chatbot.integrations.bigquery.empty_result import (
    format_empty_result,
    get_empty_attempts,
    note_empty_result,
    reset_empty_attempts,
    restore_empty_attempts,
)
from chatbot.integrations.bigquery.tables import ORDERS
from chatbot.integrations.bigquery.tools import execute_run_sql


def test_format_empty_result_requires_repair_then_exhausts() -> None:
    first = format_empty_result(
        attempt=1,
        max_attempts=2,
        sql=f"SELECT 1 FROM {ORDERS} WHERE 1=0",
    )
    assert "status: empty_result" in first
    assert "repair_required: true" in first

    last = format_empty_result(attempt=2, max_attempts=2, sql="SELECT 1")
    assert "status: empty_result_exhausted" in last
    assert "repair_required: false" in last


def test_empty_attempts_context_budget() -> None:
    token = reset_empty_attempts()
    try:
        assert get_empty_attempts() == 0
        assert note_empty_result() == 1
        assert note_empty_result() == 2
        assert get_empty_attempts() == 2
    finally:
        restore_empty_attempts(token)
    assert get_empty_attempts() == 0


def test_run_sql_empty_returns_structured_repair() -> None:
    token = reset_empty_attempts()
    try:
        with patch(
            "chatbot.integrations.bigquery.tools.run_query",
            return_value={
                "row_count": 0,
                "truncated": False,
                "bytes_billed": 0,
                "rows": [],
            },
        ):
            text = execute_run_sql(f"SELECT order_id FROM {ORDERS} WHERE 1=0")
        assert "status: empty_result" in text
        assert "repair_required: true" in text
        assert get_empty_attempts() == 1

        with patch(
            "chatbot.integrations.bigquery.tools.run_query",
            return_value={
                "row_count": 0,
                "truncated": False,
                "bytes_billed": 0,
                "rows": [],
            },
        ):
            text2 = execute_run_sql(f"SELECT order_id FROM {ORDERS} WHERE 1=0")

        assert "empty_result_exhausted" in text2
    finally:
        restore_empty_attempts(token)


def test_run_sql_reject_marks_repair_required() -> None:
    text = execute_run_sql("DELETE FROM t")
    assert "status: sql_rejected" in text
    assert "repair_required: true" in text
