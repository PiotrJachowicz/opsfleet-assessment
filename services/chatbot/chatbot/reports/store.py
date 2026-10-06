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
from chatbot.middleware.metrics import record_report_delete
from chatbot.middleware.pii import sanitize_pii

_engine = None
_SessionLocal: sessionmaker[Session] | None = None
_conversation_id_ctx: ContextVar[uuid.UUID | None] = ContextVar(
    "conversation_id", default=None
)
_pending_lock = Lock()
_pending_deletions: dict[str, "PendingDeletion"] = {}


@dataclass(frozen=True)
class PendingReportRef:
    report_id: uuid.UUID
    title: str
    file_path: str


@dataclass(frozen=True)
class PendingDeletion:
    reports: tuple[PendingReportRef, ...]

    @property
    def report_id(self) -> uuid.UUID:
        """Back-compat for single-report pending deletes."""
        return self.reports[0].report_id

    @property
    def title(self) -> str:
        return self.reports[0].title

    @property
    def file_path(self) -> str:
        return self.reports[0].file_path


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


def normalize_mentioned_clients(clients: list[str] | None) -> list[str]:
    """Strip, sanitize, lowercase, and de-dupe while preserving first-seen order."""
    if not clients:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in clients:
        if raw is None:
            continue
        cleaned = sanitize_pii(str(raw).strip())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


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


def _report_to_dict(row: Report, *, include_html: bool = False) -> dict:
    payload = {
        "report_id": str(row.id),
        "title": row.title,
        "file_path": row.file_path,
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "mentioned_clients": list(row.mentioned_clients or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if include_html:
        path = Path(row.file_path)
        if not path.is_file():
            raise FileNotFoundError(f"report file missing: {path}")
        payload["html"] = path.read_text(encoding="utf-8")
    return payload


def create_report(
    *,
    title: str,
    body_html: str,
    mentioned_clients: list[str] | None = None,
) -> dict:
    user_id = _require_user_id()
    auth = get_auth_context()
    user_label = (auth.name if auth and auth.name else user_id) or user_id
    report_id = uuid.uuid4()
    safe_title = sanitize_pii(title.strip()) or "Untitled report"
    clients = normalize_mentioned_clients(mentioned_clients)
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
            mentioned_clients=clients,
        )
        session.add(row)
        session.commit()
        created_at = row.created_at

    return {
        "report_id": str(report_id),
        "title": safe_title,
        "file_path": str(path.resolve()),
        "conversation_id": str(conversation_id) if conversation_id else None,
        "mentioned_clients": clients,
        "created_at": created_at.isoformat() if created_at else None,
    }


def list_reports_for_user(
    *,
    conversation_id: str | None = None,
    this_conversation: bool = False,
    mentioned_client: str | None = None,
) -> list[dict]:
    user_id = _require_user_id()
    stmt = select(Report).where(Report.user_id == user_id)

    if this_conversation:
        current = get_conversation_id()
        if current is None:
            return []
        stmt = stmt.where(Report.conversation_id == current)
    elif conversation_id:
        try:
            cid = uuid.UUID(conversation_id.strip())
        except ValueError as exc:
            raise ValueError("invalid conversation_id") from exc
        stmt = stmt.where(Report.conversation_id == cid)

    if mentioned_client and mentioned_client.strip():
        needle = normalize_mentioned_clients([mentioned_client])
        if not needle:
            return []
        # Stored tags are lowercased; ARRAY.any → value = ANY(column).
        stmt = stmt.where(Report.mentioned_clients.any(needle[0]))

    stmt = stmt.order_by(Report.created_at.desc())
    with _get_sync_session() as session:
        rows = session.scalars(stmt).all()
        return [_report_to_dict(r) for r in rows]


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
        return _report_to_dict(row, include_html=True)


def _stage_pending(user_id: str, reports: list[dict]) -> dict:
    refs = tuple(
        PendingReportRef(
            report_id=uuid.UUID(str(r["report_id"])),
            title=str(r["title"]),
            file_path=str(r["file_path"]),
        )
        for r in reports
    )
    pending = PendingDeletion(reports=refs)
    with _pending_lock:
        _pending_deletions[user_id] = pending
    summary = [
        {
            "report_id": str(ref.report_id),
            "title": ref.title,
            "file_path": ref.file_path,
        }
        for ref in refs
    ]
    count = len(refs)
    noun = "report" if count == 1 else "reports"
    record_report_delete("proposed")
    return {
        "status": "awaiting_confirmation",
        "count": count,
        "reports": summary,
        "instruction": (
            f"Reply with exactly y (lowercase) on its own line to permanently delete "
            f"these {count} {noun}. Any other reply cancels the pending deletion. "
            "The server—not the model—enforces this confirmation."
        ),
    }


def propose_delete_report(report_id: str) -> dict:
    """Stage a single-report deletion for confirmation. Does not delete."""
    meta = get_report_for_user(report_id)
    user_id = _require_user_id()
    return _stage_pending(user_id, [meta])


def propose_delete_reports(
    *,
    conversation_id: str | None = None,
    this_conversation: bool = False,
    mentioned_client: str | None = None,
) -> dict:
    """Stage a bulk deletion by conversation and/or mentioned client. Does not delete."""
    if not this_conversation and not (conversation_id and conversation_id.strip()) and not (
        mentioned_client and mentioned_client.strip()
    ):
        raise ValueError(
            "provide this_conversation=true, conversation_id, and/or mentioned_client"
        )

    rows = list_reports_for_user(
        conversation_id=conversation_id or None,
        this_conversation=this_conversation,
        mentioned_client=mentioned_client or None,
    )
    if not rows:
        return {
            "status": "none_matched",
            "count": 0,
            "reports": [],
            "message": "No owned reports matched the given filters.",
        }

    user_id = _require_user_id()
    return _stage_pending(user_id, rows)


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
        deleted: list[dict] = []
        errors: list[str] = []
        for ref in pending.reports:
            try:
                deleted.append(delete_report_for_user(ref.report_id, user_id))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{ref.title} ({ref.report_id}): {exc}")
        if not deleted and errors:
            record_report_delete("error")
            return {
                "handled": True,
                "outcome": "error",
                "message": "Could not delete reports: " + "; ".join(errors),
            }
        lines = [
            f"Deleted report “{item['title']}” ({item['report_id']})."
            for item in deleted
        ]
        if errors:
            lines.append("Some deletes failed: " + "; ".join(errors))
        record_report_delete("confirmed")
        return {
            "handled": True,
            "outcome": "deleted",
            "message": "\n".join(lines),
        }

    # Any non-y reply while pending cancels; agent may still handle the message.
    clear_pending_deletion(user_id)
    titles = ", ".join(f"“{ref.title}” ({ref.report_id})" for ref in pending.reports)
    record_report_delete("cancelled")
    return {
        "handled": False,
        "outcome": "cancelled",
        "message": f"Cancelled pending deletion of {titles}.",
    }
