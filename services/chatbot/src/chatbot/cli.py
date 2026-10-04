from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from typing import Any

import httpx

from chatbot.config import get_settings


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


def _check_health(client: httpx.Client, base_url: str) -> None:
    try:
        response = client.get(f"{base_url.rstrip('/')}/health")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Server unreachable at {base_url}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    payload = response.json()
    if payload.get("status") != "ok":
        print(f"Unexpected health response: {payload}", file=sys.stderr)
        raise SystemExit(1)


def _send_chat(
    client: httpx.Client,
    *,
    base_url: str,
    user_id: str,
    message: str,
    conversation_id: str | None,
) -> str | None:
    body: dict[str, Any] = {"user_id": user_id, "message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id

    with client.stream(
        "POST",
        f"{base_url.rstrip('/')}/chat",
        json=body,
        headers={"accept": "text/event-stream"},
    ) as response:
        if response.status_code == 404:
            detail = response.read().decode()
            print(f"\nError: conversation not found ({detail})", file=sys.stderr)
            return conversation_id
        if response.status_code >= 400:
            detail = response.read().decode()
            print(f"\nError: HTTP {response.status_code}: {detail}", file=sys.stderr)
            return conversation_id

        current_section: str | None = None
        for event, data in _iter_sse(response):
            if event == "meta":
                try:
                    conversation_id = json.loads(data)["conversation_id"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            elif event == "thinking":
                if current_section != "thinking":
                    if current_section is not None:
                        print()
                    print("Thinking> ", end="", flush=True)
                    current_section = "thinking"
                print(data, end="", flush=True)
            elif event == "token":
                if current_section != "token":
                    if current_section is not None:
                        print()
                    print("Assistant> ", end="", flush=True)
                    current_section = "token"
                print(data, end="", flush=True)
            elif event == "tool":
                if current_section is not None:
                    print()
                    current_section = None
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    print(f"Tool> {data}", flush=True)
                else:
                    name = payload.get("name", "tool")
                    status = payload.get("status", "")
                    if status == "start":
                        detail = payload.get("input") or ""
                        print(f"Tool> {name} start {detail}", flush=True)
                    else:
                        detail = payload.get("output_preview") or ""
                        print(f"Tool> {name} end {detail}", flush=True)
            elif event == "error":
                try:
                    detail = json.loads(data).get("detail", data)
                except json.JSONDecodeError:
                    detail = data
                if current_section is not None:
                    print()
                print(f"Error: {detail}", file=sys.stderr)
                current_section = None
            elif event == "done":
                try:
                    conversation_id = json.loads(data).get(
                        "conversation_id", conversation_id
                    )
                except json.JSONDecodeError:
                    pass
        if current_section is not None:
            print()

    return conversation_id


def main() -> None:
    settings = get_settings()
    base_url = settings.chat_base_url
    user_id = settings.chat_user_id
    conversation_id: str | None = None

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
        _check_health(client, base_url)

        print("Chatbot CLI")
        print(f"Server: {base_url}")
        print(f"User:   {user_id}")
        print("Commands: /new  /quit")
        print()

        while True:
            try:
                user_input = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                return

            if not user_input:
                continue
            if user_input in {"/quit", "/exit", "/q"}:
                print("Bye.")
                return
            if user_input == "/new":
                conversation_id = None
                print("Started a new conversation.")
                continue

            conversation_id = _send_chat(
                client,
                base_url=base_url,
                user_id=user_id,
                message=user_input,
                conversation_id=conversation_id,
            )
            if conversation_id:
                print(f"(conversation_id={conversation_id})")


if __name__ == "__main__":
    main()
