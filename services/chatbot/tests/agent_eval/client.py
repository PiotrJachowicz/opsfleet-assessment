"""HTTP/SSE client that drives the running chatbot service."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from chatbot.auth import PRESET_USERS, mint_access_token


@dataclass
class ToolCall:
    name: str
    status: str
    detail: str = ""


@dataclass
class AgentRun:
    case_id: int
    answer: str = ""
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    conversation_id: str = ""
    error: str | None = None
    latency_s: float = 0.0


def _iter_sse(response: httpx.Response) -> Iterator[tuple[str, str]]:
    event = "message"
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "":
            if data_lines:
                yield event, "\n".join(data_lines)
            event = "message"
            data_lines = []
    if data_lines:
        yield event, "\n".join(data_lines)


class ChatbotAgent:
    """Invoke the live ``POST /chat`` SSE endpoint and capture answer + tool trace."""

    def __init__(
        self,
        *,
        base_url: str,
        jwt_secret: str,
        timeout_s: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.jwt_secret = jwt_secret
        self.timeout_s = timeout_s

    def healthcheck(self) -> None:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{self.base_url}/health")
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "ok":
                raise RuntimeError(f"unexpected health payload: {payload}")

    def invoke(
        self,
        case_id: int,
        question: str,
        *,
        auth_preset: str = "admin",
        conversation_id: str | None = None,
    ) -> AgentRun:
        if auth_preset not in PRESET_USERS:
            raise ValueError(f"unknown auth_preset: {auth_preset}")
        access_token = mint_access_token(
            preset_key=auth_preset, secret=self.jwt_secret
        )
        user_id = str(PRESET_USERS[auth_preset]["sub"])
        started = time.perf_counter()
        run = AgentRun(case_id=case_id, conversation_id=conversation_id or "")
        answer_parts: list[str] = []
        thinking_parts: list[str] = []

        body: dict[str, Any] = {"user_id": user_id, "message": question}
        if conversation_id:
            body["conversation_id"] = conversation_id

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/chat",
                    json=body,
                    headers={
                        "accept": "text/event-stream",
                        "authorization": f"Bearer {access_token}",
                    },
                ) as response:
                    if response.status_code >= 400:
                        detail = response.read().decode(errors="replace")
                        run.error = f"HTTP {response.status_code}: {detail}"
                        run.latency_s = time.perf_counter() - started
                        return run

                    for event, data in _iter_sse(response):
                        if event == "meta":
                            try:
                                run.conversation_id = str(
                                    json.loads(data).get("conversation_id") or ""
                                )
                            except (json.JSONDecodeError, TypeError):
                                pass
                        elif event == "token":
                            answer_parts.append(data)
                        elif event == "thinking":
                            thinking_parts.append(data)
                        elif event == "tool":
                            try:
                                payload: dict[str, Any] = json.loads(data)
                            except json.JSONDecodeError:
                                run.tool_calls.append(
                                    ToolCall(name="tool", status="unknown", detail=data)
                                )
                            else:
                                status = str(payload.get("status") or "")
                                detail = str(
                                    payload.get("input")
                                    or payload.get("output_preview")
                                    or ""
                                )
                                run.tool_calls.append(
                                    ToolCall(
                                        name=str(payload.get("name") or "tool"),
                                        status=status,
                                        detail=detail,
                                    )
                                )
                        elif event == "error":
                            try:
                                run.error = str(json.loads(data).get("detail") or data)
                            except json.JSONDecodeError:
                                run.error = data
        except Exception as exc:  # noqa: BLE001 - capture into run
            run.error = str(exc)

        run.answer = "".join(answer_parts).strip()
        run.thinking = "".join(thinking_parts).strip()
        run.latency_s = time.perf_counter() - started
        return run

    def invoke_case(
        self,
        case_id: int,
        question: str,
        *,
        auth_preset: str = "admin",
        turns: list[str] | None = None,
    ) -> AgentRun:
        """Run one or more turns on a single conversation; merge answers/tools."""
        script = list(turns) if turns else [question]
        conversation_id: str | None = None
        merged = AgentRun(case_id=case_id)
        answers: list[str] = []
        total_latency = 0.0

        for i, turn in enumerate(script):
            step = self.invoke(
                case_id,
                turn,
                auth_preset=auth_preset,
                conversation_id=conversation_id,
            )
            conversation_id = step.conversation_id or conversation_id
            merged.conversation_id = conversation_id or ""
            merged.tool_calls.extend(step.tool_calls)
            total_latency += step.latency_s
            if step.answer:
                answers.append(f"[turn {i + 1}] {step.answer}")
            if step.error and not step.answer:
                merged.error = step.error
                merged.latency_s = total_latency
                merged.answer = "\n\n".join(answers)
                return merged

        merged.answer = "\n\n".join(answers)
        merged.latency_s = total_latency
        return merged
