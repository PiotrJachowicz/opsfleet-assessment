"""Bounded empty-result repair signaling for BigQuery tool calls.

Application code detects ``row_count == 0`` and returns a structured repair
directive (or exhaustion notice). Per-turn attempt budget lives in a ContextVar
so we do not loop forever or inflate BigQuery spend.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_empty_attempts: ContextVar[int] = ContextVar("bq_empty_attempts", default=0)


def reset_empty_attempts() -> Token[int]:
    return _empty_attempts.set(0)


def restore_empty_attempts(token: Token[int]) -> None:
    _empty_attempts.reset(token)


def get_empty_attempts() -> int:
    return _empty_attempts.get()


def note_empty_result() -> int:
    """Increment and return the 1-based attempt number for this empty result."""
    nxt = _empty_attempts.get() + 1
    _empty_attempts.set(nxt)
    return nxt


def format_empty_result(*, attempt: int, max_attempts: int, sql: str) -> str:
    """Build the tool payload when a query returns zero rows."""
    preview = " ".join(sql.strip().split())
    if len(preview) > 500:
        preview = preview[:497] + "..."

    if attempt >= max_attempts:
        return (
            "status: empty_result_exhausted\n"
            f"attempt: {attempt}/{max_attempts}\n"
            "row_count: 0\n"
            "repair_required: false\n"
            f"sql_preview: {preview}\n"
            "guidance: Stop rewriting SQL for this question. Tell the user that "
            "no matching rows were found after bounded repair attempts. Do not "
            "invent metrics. Suggest widening filters only as a follow-up if useful."
        )

    remaining = max_attempts - attempt
    return (
        "status: empty_result\n"
        f"attempt: {attempt}/{max_attempts}\n"
        "row_count: 0\n"
        "repair_required: true\n"
        f"sql_preview: {preview}\n"
        "guidance: Do not invent numbers. Repair the SQL and call run_sql again "
        f"(up to {remaining} more repair attempt(s)). Typical fixes: widen date "
        "windows, relax WHERE filters, fix JOINs/column names (call list_schema), "
        "or check that brand scope still allows matching products. If still empty "
        "after the budget, explain that no data matched."
    )
