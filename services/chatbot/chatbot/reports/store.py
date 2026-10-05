"""Saved HTML report artifacts (per-user library)."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from html import escape
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from chatbot.auth import get_auth_context
from chatbot.config import get_settings
from chatbot.db.models import Report
from chatbot.middleware.pii import sanitize_pii

_engine = None
_SessionLocal: sessionmaker[Session] | None = None
_conversation_id_ctx: ContextVar[uuid.UUID | None] = ContextVar(
    "conversation_id", default=None
)
_pending_lock = Lock()
_pending_deletions: dict[str, "PendingDeletion"] = {}


@dataclass(frozen=True)
class PendingDeletion:
    report_id: uuid.UUID
    title: str
    file_path: str


def set_conversation_id(conversation_id: uuid.UUID | None):
    return _conversation_id_ctx.set(conversation_id)


def reset_conversation_id(token) -> None:
    _conversation_id_ctx.reset(token)


def get_conversation_id() -> uuid.UUID | None:
    return _conversation_id_ctx.get()


def _sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def _get_sync_session() -> Session:
    global _engine, _SessionLocal
    if _SessionLocal is None:
        settings = get_settings()
        _engine = create_engine(_sync_url(settings.database_url), pool_pre_ping=True)
        _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    return _SessionLocal()


def _reports_dir() -> Path:
    settings = get_settings()
    path = Path(settings.reports_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _require_user_id() -> str:
    auth = get_auth_context()
    if auth is None or not auth.user_id:
        raise PermissionError("authenticated user required for report tools")
    return auth.user_id


def _slug(title: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
    return (cleaned or "report")[:60]


def render_report_html(*, title: str, body_html: str, user_label: str) -> str:
    safe_title = escape(sanitize_pii(title))
    safe_body = sanitize_pii(body_html)
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  <style>
    :root {{
      --ink: #1a1f16;
      --muted: #5c6654;
      --paper: #f7f3ea;
      --card: #fffdf8;
      --accent: #0f6b4c;
      --rule: #d5cbb8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Source Serif 4", "Iowan Old Style", Palatino, Georgia, serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #e8f0e4 0%, transparent 40%),
        linear-gradient(180deg, #efe8d8 0%, var(--paper) 45%, #f3eee3 100%);
      min-height: 100vh;
    }}
    .page {{
      max-width: 820px;
      margin: 0 auto;
      padding: 3rem 1.5rem 4rem;
    }}
    header {{
      border-bottom: 1px solid var(--rule);
      padding-bottom: 1.25rem;
      margin-bottom: 2rem;
    }}
    .eyebrow {{
      font-family: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
      font-size: 0.75rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--accent);
      margin: 0 0 0.75rem;
    }}
    h1 {{
      font-size: clamp(1.8rem, 4vw, 2.6rem);
      line-height: 1.15;
      margin: 0 0 0.75rem;
      font-weight: 600;
    }}
    .meta {{
      font-family: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
      font-size: 0.9rem;
      color: var(--muted);
    }}
    article {{
      background: var(--card);
      border: 1px solid var(--rule);
      border-radius: 2px;
      padding: 1.75rem 1.5rem;
      box-shadow: 0 12px 40px rgba(26, 31, 22, 0.06);
    }}
    article h2 {{
      font-size: 1.25rem;
      margin: 1.75rem 0 0.75rem;
      color: var(--accent);
    }}
    article h2:first-child {{ margin-top: 0; }}
    article p, article li {{
      line-height: 1.65;
      font-size: 1.05rem;
    }}
    article ul {{ padding-left: 1.2rem; }}
    article table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1rem 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
      font-size: 0.92rem;
    }}
    article th, article td {{
      border-bottom: 1px solid var(--rule);
      text-align: left;
      padding: 0.55rem 0.4rem;
    }}
    footer {{
      margin-top: 2rem;
      font-family: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
      font-size: 0.8rem;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <div class="page">
    <header>
      <p class="eyebrow">Retail analysis report</p>
      <h1>{safe_title}</h1>
      <p class="meta">Prepared for {escape(sanitize_pii(user_label))} · {generated}</p>
    </header>
    <article>
      {safe_body}
    </article>
    <footer>OpsFleet prototype · saved report artifact</footer>
  </div>
</body>
</html>
"""


def create_report(*, title: str, body_html: str) -> dict:
    user_id = _require_user_id()
    auth = get_auth_context()
    user_label = (auth.name if auth and auth.name else user_id) or user_id
    report_id = uuid.uuid4()
    safe_title = sanitize_pii(title.strip()) or "Untitled report"
    filename = f"{_slug(safe_title)}-{report_id.hex[:8]}.html"
    path = _reports_dir() / filename
    html = render_report_html(
        title=safe_title, body_html=body_html, user_label=user_label
    )
    path.write_text(html, encoding="utf-8")

    conversation_id = get_conversation_id()
    with _get_sync_session() as session:
        row = Report(
            id=report_id,
            user_id=user_id,
            title=safe_title,
            file_path=str(path.resolve()),
            conversation_id=conversation_id,
        )
        session.add(row)
        session.commit()
        created_at = row.created_at

    return {
        "report_id": str(report_id),
        "title": safe_title,
        "file_path": str(path.resolve()),
        "created_at": created_at.isoformat() if created_at else None,
    }


def list_reports_for_user() -> list[dict]:
    user_id = _require_user_id()
    with _get_sync_session() as session:
        rows = session.scalars(
            select(Report)
            .where(Report.user_id == user_id)
            .order_by(Report.created_at.desc())
        ).all()
        return [
            {
                "report_id": str(r.id),
                "title": r.title,
                "file_path": r.file_path,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def get_report_for_user(report_id: str) -> dict:
    user_id = _require_user_id()
    try:
        rid = uuid.UUID(report_id)
    except ValueError as exc:
        raise ValueError("invalid report_id") from exc

    with _get_sync_session() as session:
        row = session.scalar(
            select(Report).where(Report.id == rid, Report.user_id == user_id)
        )
        if row is None:
            raise PermissionError("report not found or not owned by this user")
        path = Path(row.file_path)
        if not path.is_file():
            raise FileNotFoundError(f"report file missing: {path}")
        html = path.read_text(encoding="utf-8")
        return {
            "report_id": str(row.id),
            "title": row.title,
            "file_path": row.file_path,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "html": html,
        }


def propose_delete_report(report_id: str) -> dict:
    """Stage a deletion for confirmation. Does not delete."""
    meta = get_report_for_user(report_id)
    user_id = _require_user_id()
    pending = PendingDeletion(
        report_id=uuid.UUID(meta["report_id"]),
        title=str(meta["title"]),
        file_path=str(meta["file_path"]),
    )
    with _pending_lock:
        _pending_deletions[user_id] = pending
    return {
        "status": "awaiting_confirmation",
        "report_id": meta["report_id"],
        "title": meta["title"],
        "file_path": meta["file_path"],
        "created_at": meta.get("created_at"),
        "instruction": (
            "Reply with exactly y (lowercase) on its own line to permanently delete "
            "this report. Any other reply cancels the pending deletion. "
            "The server—not the model—enforces this confirmation."
        ),
    }


def clear_pending_deletion(user_id: str) -> PendingDeletion | None:
    with _pending_lock:
        return _pending_deletions.pop(user_id, None)


def get_pending_deletion(user_id: str) -> PendingDeletion | None:
    with _pending_lock:
        return _pending_deletions.get(user_id)


def is_delete_confirmation(message: str) -> bool:
    """Deterministic gate: only an exact trimmed lowercase 'y' confirms."""
    return message.strip() == "y"


def delete_report_for_user(report_id: uuid.UUID, user_id: str) -> dict:
    """Delete DB row + file. Caller must have already verified confirmation."""
    with _get_sync_session() as session:
        row = session.scalar(
            select(Report).where(Report.id == report_id, Report.user_id == user_id)
        )
        if row is None:
            raise PermissionError("report not found or not owned by this user")
        title = row.title
        path = Path(row.file_path)
        session.execute(
            delete(Report).where(Report.id == report_id, Report.user_id == user_id)
        )
        session.commit()
    if path.is_file():
        path.unlink()
    return {"report_id": str(report_id), "title": title, "deleted": True}


def try_resolve_pending_deletion(user_id: str, message: str) -> dict | None:
    """If a deletion is pending, handle confirm/cancel in application code.

    Returns a result dict when the turn was fully handled (no agent needed),
    or None when the agent should run normally.
    """
    pending = get_pending_deletion(user_id)
    if pending is None:
        return None

    if is_delete_confirmation(message):
        clear_pending_deletion(user_id)
        try:
            deleted = delete_report_for_user(pending.report_id, user_id)
        except Exception as exc:  # noqa: BLE001
            return {
                "handled": True,
                "outcome": "error",
                "message": f"Could not delete report: {exc}",
            }
        return {
            "handled": True,
            "outcome": "deleted",
            "message": (
                f"Deleted report “{deleted['title']}” "
                f"({deleted['report_id']})."
            ),
        }

    # Any non-y reply while pending cancels; agent may still handle the message.
    clear_pending_deletion(user_id)
    return {
        "handled": False,
        "outcome": "cancelled",
        "message": (
            f"Cancelled pending deletion of “{pending.title}” "
            f"({pending.report_id})."
        ),
    }
