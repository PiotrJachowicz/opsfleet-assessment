"""LangChain tools for creating and reading per-user HTML reports."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from chatbot.middleware.pii import sanitize_pii
from chatbot.reports.store import (
    create_report,
    get_report_for_user,
    list_reports_for_user,
)


@tool
def create_html_report(title: str, body_html: str) -> str:
    """Save an executive HTML report artifact for the current user.

    Pass a short title and HTML body fragments only (h2/p/ul/table — no full
    document). The service wraps content in a styled template, stores the file
    under output/reports, and records ownership in the database.
    Use this when the user asks to create or save a report.
    """
    try:
        result = create_report(title=title, body_html=body_html)
    except Exception as exc:  # noqa: BLE001
        return sanitize_pii(f"Failed to create report: {exc}")
    return sanitize_pii(
        "Report saved.\n"
        + json.dumps(result, indent=2)
        + "\nTell the user the report_id and that they can list_reports / get_report."
    )


@tool
def list_reports() -> str:
    """List HTML reports owned by the current authenticated user (newest first)."""
    try:
        rows = list_reports_for_user()
    except Exception as exc:  # noqa: BLE001
        return sanitize_pii(f"Failed to list reports: {exc}")
    if not rows:
        return "No saved reports for this user."
    return sanitize_pii(json.dumps(rows, indent=2))


@tool
def get_report(report_id: str) -> str:
    """Load one HTML report by id if it belongs to the current user.

    Returns metadata and the full HTML so it can be shown or summarized.
    """
    try:
        payload = get_report_for_user(report_id)
    except Exception as exc:  # noqa: BLE001
        return sanitize_pii(f"Failed to get report: {exc}")
    return sanitize_pii(json.dumps(payload, indent=2))
