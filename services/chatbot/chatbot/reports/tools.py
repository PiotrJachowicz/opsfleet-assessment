"""LangChain tools for creating and reading per-user HTML reports."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from chatbot.middleware.pii import sanitize_pii
from chatbot.reports import store as report_store


@tool
def create_html_report(title: str, body_html: str) -> str:
    """Save an executive HTML report artifact for the current user.

    Pass a short title and HTML body fragments only (h2/p/ul/table — no full
    document). The service wraps content in a styled template, stores the file
    under output/reports, and records ownership in the database.
    Use this when the user asks to create or save a report.
    """
    try:
        result = report_store.create_report(title=title, body_html=body_html)
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
        rows = report_store.list_reports_for_user()
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
        payload = report_store.get_report_for_user(report_id)
    except Exception as exc:  # noqa: BLE001
        return sanitize_pii(f"Failed to get report: {exc}")
    return sanitize_pii(json.dumps(payload, indent=2))


@tool
def propose_delete_report(report_id: str) -> str:
    """Start deletion of one of the current user's reports (confirmation required).

    Shows report details and stages a pending delete. The user must reply with
    exactly `y` in a following message; the server deletes only then. There is
    no tool that deletes immediately — do not claim a report was deleted until
    the user confirms with `y`.
    """
    try:
        payload = report_store.propose_delete_report(report_id)
    except Exception as exc:  # noqa: BLE001
        return sanitize_pii(f"Failed to propose delete: {exc}")
    return sanitize_pii(
        "Deletion staged — awaiting confirmation.\n"
        + json.dumps(payload, indent=2)
        + "\nTell the user the title/id/path and that they must reply with exactly "
        "`y` to delete (anything else cancels). Do NOT say the report is deleted yet."
    )
