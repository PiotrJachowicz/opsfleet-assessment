import json
import logging
from contextlib import asynccontextmanager

from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from chatbot.auth import AuthError, auth_context_from_authorization
from chatbot.chat import get_owned_conversation, stream_chat_turn
from chatbot.config import get_settings
from chatbot.db import SessionLocal
from chatbot.logging_setup import configure_logging
from chatbot.models import ChatRequest
from chatbot.tracing import configure_langsmith

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: Starlette):
    settings = get_settings()
    configure_logging(settings)
    configure_langsmith(settings)
    yield


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def chat(request: Request) -> JSONResponse | EventSourceResponse:
    settings = get_settings()
    try:
        auth = auth_context_from_authorization(
            request.headers.get("authorization"),
            settings.jwt_secret,
        )
    except AuthError as exc:
        logger.warning("chat auth failed: %s", exc)
        return JSONResponse({"detail": str(exc)}, status_code=401)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        logger.warning("chat rejected: invalid JSON body")
        return JSONResponse({"detail": "invalid JSON body"}, status_code=400)

    if isinstance(payload, dict):
        # Identity comes from the JWT; body user_id is ignored if present.
        payload = {**payload, "user_id": auth.user_id}

    try:
        body = ChatRequest.model_validate(payload)
    except ValidationError as exc:
        logger.warning("chat rejected: validation error user_id=%s", auth.user_id)
        return JSONResponse({"detail": exc.errors()}, status_code=422)

    if body.conversation_id is not None:
        async with SessionLocal() as session:
            conversation = await get_owned_conversation(
                session,
                conversation_id=body.conversation_id,
                user_id=body.user_id,
            )
            if conversation is None:
                logger.info(
                    "chat conversation not found user_id=%s conversation_id=%s",
                    body.user_id,
                    body.conversation_id,
                )
                return JSONResponse(
                    {"detail": "conversation not found"},
                    status_code=404,
                )

    logger.info(
        "chat turn start user_id=%s conversation_id=%s brands=%s",
        auth.user_id,
        body.conversation_id,
        ",".join(auth.allowed_brands),
    )

    async def event_generator():
        async with SessionLocal() as session:
            async for event in stream_chat_turn(session, body, auth):
                if await request.is_disconnected():
                    logger.info(
                        "chat client disconnected user_id=%s conversation_id=%s",
                        auth.user_id,
                        body.conversation_id,
                    )
                    break
                yield event

    return EventSourceResponse(event_generator())


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/chat", chat, methods=["POST"]),
    ],
)
