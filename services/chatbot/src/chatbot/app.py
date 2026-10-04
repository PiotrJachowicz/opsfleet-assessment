import asyncio
import json

from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from chatbot.chat import get_owned_conversation, stream_chat_turn
from chatbot.db import SessionLocal
from chatbot.schemas import ChatRequest


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def hello(request: Request) -> EventSourceResponse:
    async def event_generator():
        for i in range(1, 4):
            if await request.is_disconnected():
                break
            yield {"event": "message", "data": f"Hello {i}"}
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


async def chat(request: Request) -> JSONResponse | EventSourceResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"detail": "invalid JSON body"}, status_code=400)

    try:
        body = ChatRequest.model_validate(payload)
    except ValidationError as exc:
        return JSONResponse({"detail": exc.errors()}, status_code=422)

    if body.conversation_id is not None:
        async with SessionLocal() as session:
            conversation = await get_owned_conversation(
                session,
                conversation_id=body.conversation_id,
                user_id=body.user_id,
            )
            if conversation is None:
                return JSONResponse(
                    {"detail": "conversation not found"},
                    status_code=404,
                )

    async def event_generator():
        async with SessionLocal() as session:
            async for event in stream_chat_turn(session, body):
                if await request.is_disconnected():
                    break
                yield event

    return EventSourceResponse(event_generator())


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/hello", hello, methods=["GET"]),
        Route("/chat", chat, methods=["POST"]),
    ]
)
