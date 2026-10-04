import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chatbot.config import get_settings
from chatbot.llm import create_chat_model
from chatbot.models import Conversation, Message, MessageRole
from chatbot.schemas import ChatRequest


def _chunk_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            elif hasattr(block, "text"):
                parts.append(str(getattr(block, "text") or ""))
        return "".join(parts)
    return str(content or "")


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


async def stream_chat_turn(
    session: AsyncSession,
    request: ChatRequest,
) -> AsyncIterator[dict]:
    settings = get_settings()
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

    session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.user,
            content=request.message,
        )
    )
    conversation.updated_at = datetime.now(UTC)
    await session.commit()

    yield {
        "event": "meta",
        "data": json.dumps({"conversation_id": str(conversation.id)}),
    }

    history_result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    )
    history = list(history_result.scalars().all())
    lc_messages = _to_langchain_messages(history)

    model = create_chat_model(settings)
    chunks: list[str] = []
    try:
        async for chunk in model.astream(lc_messages):
            text = _chunk_text(chunk.content)
            if not text:
                continue
            chunks.append(text)
            yield {"event": "token", "data": text}
    except asyncio.CancelledError:
        await _persist_assistant(
            session, conversation=conversation, content="".join(chunks)
        )
        raise
    except Exception as exc:  # noqa: BLE001 - surface to SSE client
        yield {"event": "error", "data": json.dumps({"detail": str(exc)})}
        return

    await _persist_assistant(
        session, conversation=conversation, content="".join(chunks)
    )
    yield {
        "event": "done",
        "data": json.dumps({"conversation_id": str(conversation.id)}),
    }
