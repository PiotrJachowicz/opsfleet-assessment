import asyncio

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


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


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/hello", hello, methods=["GET"]),
    ]
)
