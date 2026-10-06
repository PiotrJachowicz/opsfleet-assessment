import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chatbot.agent import agent_config, get_analysis_agent
from chatbot.auth import AuthContext, reset_auth_context, set_auth_context
from chatbot.config import get_settings
from chatbot.db import Conversation, Message, MessageRole
from chatbot.middleware.pii import PiiStreamSanitizer, sanitize_pii
from chatbot.models import ChatRequest
from chatbot.integrations.bigquery.empty_result import (
    reset_empty_attempts,
    restore_empty_attempts,
)
from chatbot.reports.store import (
    reset_conversation_id,
    set_conversation_id,
    try_resolve_pending_deletion,
)

logger = logging.getLogger(__name__)


def _iter_chunk_parts(content: Any) -> Iterator[tuple[str, str]]:
    """Yield (event_name, text) parts from a LangChain chunk content value."""
    if isinstance(content, str):
        if content:
            yield "token", content
        return

    if not isinstance(content, list):
        text = str(content or "")
        if text:
            yield "token", text
        return

    for block in content:
        if isinstance(block, str):
            if block:
                yield "token", block
            continue
        if not isinstance(block, dict):
            if hasattr(block, "text") and getattr(block, "text"):
                yield "token", str(block.text)
            continue

        block_type = block.get("type")
        if block_type in {"thinking", "reasoning"}:
            text = block.get("thinking") or block.get("reasoning") or ""
            if text:
                yield "thinking", str(text)
            continue
        if "text" in block and block.get("text"):
            yield "token", str(block["text"])


def _message_text(content: Any) -> str:
    return "".join(text for event, text in _iter_chunk_parts(content) if event == "token")


def _to_langchain_messages(rows: list[Message]) -> list[BaseMessage]:
    mapped: list[BaseMessage] = []
    for row in rows:
        if row.role is MessageRole.user:
            mapped.append(HumanMessage(content=row.content))
        elif row.role is MessageRole.assistant:
            mapped.append(AIMessage(content=row.content))
        else:
            mapped.append(SystemMessage(content=row.content))
    return mapped


async def get_owned_conversation(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    user_id: str,
) -> Conversation | None:
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _persist_assistant(
    session: AsyncSession,
    *,
    conversation: Conversation,
    content: str,
) -> None:
    if not content:
        return
    session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=content,
        )
    )
    conversation.updated_at = datetime.now(UTC)
    await session.commit()


def _preview(value: Any, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = sanitize_pii(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


async def stream_chat_turn(
    session: AsyncSession,
    request: ChatRequest,
    auth: AuthContext,
) -> AsyncIterator[dict]:
    settings = get_settings()
    auth_token = set_auth_context(auth)
    convo_token = set_conversation_id(None)
    empty_token = reset_empty_attempts()
    try:
        async for event in _stream_chat_turn_inner(session, request, settings):
            yield event
    finally:
        restore_empty_attempts(empty_token)
        reset_conversation_id(convo_token)
        reset_auth_context(auth_token)


async def _stream_chat_turn_inner(
    session: AsyncSession,
    request: ChatRequest,
    settings,
) -> AsyncIterator[dict]:
    if not settings.gemini_api_key:
        yield {
            "event": "error",
            "data": json.dumps({"detail": "GEMINI_API_KEY is not configured"}),
        }
        return

    if request.conversation_id is None:
        conversation = Conversation(user_id=request.user_id)
        session.add(conversation)
        await session.flush()
    else:
        conversation = await get_owned_conversation(
            session,
            conversation_id=request.conversation_id,
            user_id=request.user_id,
        )
        if conversation is None:
            raise LookupError("conversation not found")

    set_conversation_id(conversation.id)

    safe_message = sanitize_pii(request.message)
    session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.user,
            content=safe_message,
        )
    )
    conversation.updated_at = datetime.now(UTC)
    await session.commit()

    yield {
        "event": "meta",
        "data": json.dumps({"conversation_id": str(conversation.id)}),
    }

    # Deterministic delete confirmation: only an exact "y" deletes, in app code.
    pending_result = try_resolve_pending_deletion(request.user_id, safe_message)
    if pending_result is not None and pending_result.get("handled"):
        logger.info(
            "chat delete confirmed user_id=%s conversation_id=%s outcome=%s",
            request.user_id,
            conversation.id,
            pending_result.get("outcome"),
        )
        reply = sanitize_pii(str(pending_result["message"]))
        await _persist_assistant(
            session, conversation=conversation, content=reply
        )
        yield {"event": "token", "data": reply}
        yield {
            "event": "done",
            "data": json.dumps({"conversation_id": str(conversation.id)}),
        }
        return
    if pending_result is not None and pending_result.get("outcome") == "cancelled":
        logger.info(
            "chat delete cancelled user_id=%s conversation_id=%s",
            request.user_id,
            conversation.id,
        )
        # Surface cancel notice, then continue so the new message can be handled.
        cancel_note = sanitize_pii(str(pending_result["message"]))
        yield {"event": "token", "data": cancel_note + "\n\n"}

    history_result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    )
    history = list(history_result.scalars().all())
    lc_messages = _to_langchain_messages(history)

    agent = get_analysis_agent()
    final_answer_parts: list[str] = []
    token_sanitizer = PiiStreamSanitizer()
    thinking_sanitizer = PiiStreamSanitizer()
    try:
        async for event in agent.astream_events(
            {"messages": lc_messages},
            config=agent_config(settings),
            version="v2",
        ):
            kind = event.get("event")
            data = event.get("data") or {}

            if kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk is None:
                    continue
                for event_name, text in _iter_chunk_parts(chunk.content):
                    if event_name == "thinking":
                        safe = thinking_sanitizer.push(text)
                    else:
                        safe = token_sanitizer.push(text)
                    if safe:
                        yield {"event": event_name, "data": safe}

            elif kind == "on_chat_model_end":
                for event_name, sanitizer in (
                    ("thinking", thinking_sanitizer),
                    ("token", token_sanitizer),
                ):
                    tail = sanitizer.finalize()
                    if tail:
                        yield {"event": event_name, "data": tail}

                output = data.get("output")
                if isinstance(output, AIMessage) and not output.tool_calls:
                    text = sanitize_pii(_message_text(output.content))
                    if text:
                        final_answer_parts.append(text)

            elif kind == "on_tool_start":
                tool_name = event.get("name") or data.get("name") or "tool"
                logger.info(
                    "chat tool start user_id=%s conversation_id=%s tool=%s",
                    request.user_id,
                    conversation.id,
                    tool_name,
                )
                yield {
                    "event": "tool",
                    "data": json.dumps(
                        {
                            "name": tool_name,
                            "status": "start",
                            "input": _preview(data.get("input")),
                        }
                    ),
                }

            elif kind == "on_tool_end":
                tool_name = event.get("name") or "tool"
                logger.info(
                    "chat tool end user_id=%s conversation_id=%s tool=%s",
                    request.user_id,
                    conversation.id,
                    tool_name,
                )
                yield {
                    "event": "tool",
                    "data": json.dumps(
                        {
                            "name": tool_name,
                            "status": "end",
                            "output_preview": _preview(data.get("output")),
                        }
                    ),
                }
    except asyncio.CancelledError:
        logger.warning(
            "chat turn cancelled user_id=%s conversation_id=%s",
            request.user_id,
            conversation.id,
        )
        await _persist_assistant(
            session,
            conversation=conversation,
            content=sanitize_pii("\n".join(final_answer_parts).strip()),
        )
        raise
    except Exception as exc:  # noqa: BLE001 - surface to SSE client
        logger.exception(
            "chat turn failed user_id=%s conversation_id=%s",
            request.user_id,
            conversation.id,
        )
        yield {
            "event": "error",
            "data": json.dumps({"detail": sanitize_pii(str(exc))}),
        }
        return

    await _persist_assistant(
        session,
        conversation=conversation,
        content=sanitize_pii("\n".join(final_answer_parts).strip()),
    )
    logger.info(
        "chat turn done user_id=%s conversation_id=%s",
        request.user_id,
        conversation.id,
    )
    yield {
        "event": "done",
        "data": json.dumps({"conversation_id": str(conversation.id)}),
    }
