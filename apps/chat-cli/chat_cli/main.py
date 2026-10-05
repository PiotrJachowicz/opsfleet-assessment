from __future__ import annotations

import itertools
import json
import sys
import threading
from collections.abc import Iterator
from typing import Any

import httpx

from chat_cli.auth import PRESET_USERS, format_presets, mint_access_token
from chat_cli.config import get_settings


class _DotsSpinner:
    """Animate '.', '..', '...' on one line until stopped."""

    def __init__(self, interval_s: float = 0.4) -> None:
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._active = False

    def start(self) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._stop.set()
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=1.0)
        # Clear the spinner line.
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _run(self) -> None:
        frames = itertools.cycle([".", "..", "..."])
        while not self._stop.is_set():
            frame = next(frames)
            sys.stdout.write(f"\r{frame}\033[K")
            sys.stdout.flush()
            if self._stop.wait(self._interval_s):
                break


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
    token: str,
    user_id: str,
    message: str,
    conversation_id: str | None,
) -> str | None:
    body: dict[str, Any] = {"user_id": user_id, "message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id

    spinner = _DotsSpinner()
    spinner.start()
    try:
        with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/chat",
            json=body,
            headers={
                "accept": "text/event-stream",
                "authorization": f"Bearer {token}",
            },
        ) as response:
            if response.status_code == 401:
                spinner.stop()
                detail = response.read().decode()
                print(f"Auth error: {detail}", file=sys.stderr)
                return conversation_id
            if response.status_code == 404:
                spinner.stop()
                detail = response.read().decode()
                print(f"Error: conversation not found ({detail})", file=sys.stderr)
                return conversation_id
            if response.status_code >= 400:
                spinner.stop()
                detail = response.read().decode()
                print(f"Error: HTTP {response.status_code}: {detail}", file=sys.stderr)
                return conversation_id

            current_section: str | None = None
            for event, data in _iter_sse(response):
                if event == "meta":
                    try:
                        conversation_id = json.loads(data)["conversation_id"]
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
                    continue

                # First visible event ends the waiting spinner.
                spinner.stop()

                if event == "thinking":
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
    finally:
        spinner.stop()

    return conversation_id


def _print_identity(preset_key: str) -> None:
    profile = PRESET_USERS[preset_key]
    brands = ", ".join(profile["brands"])
    print(f"User:   {preset_key} ({profile['name']})  brands=[{brands}]")


def main() -> None:
    settings = get_settings()
    base_url = settings.chat_base_url
    preset_key = settings.chat_user_preset
    if preset_key not in PRESET_USERS:
        print(
            f"Unknown CHAT_USER_PRESET={preset_key!r}. Choose one of: "
            + ", ".join(PRESET_USERS),
            file=sys.stderr,
        )
        raise SystemExit(1)

    conversation_id: str | None = None
    token = mint_access_token(preset_key=preset_key, secret=settings.jwt_secret)
    user_id = PRESET_USERS[preset_key]["sub"]

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
        _check_health(client, base_url)

        print("Chatbot CLI")
        print(f"Server: {base_url}")
        _print_identity(preset_key)
        print("Commands: /new  /user <admin|calvin|levis>  /whoami  /quit")
        print("Presets:")
        print(format_presets())
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
            if user_input == "/whoami":
                _print_identity(preset_key)
                continue
            if user_input.startswith("/user"):
                parts = user_input.split(maxsplit=1)
                if len(parts) != 2 or parts[1] not in PRESET_USERS:
                    print("Usage: /user <admin|calvin|levis>")
                    continue
                preset_key = parts[1]
                token = mint_access_token(
                    preset_key=preset_key, secret=settings.jwt_secret
                )
                user_id = PRESET_USERS[preset_key]["sub"]
                conversation_id = None
                print("Switched identity; new conversation.")
                _print_identity(preset_key)
                continue

            conversation_id = _send_chat(
                client,
                base_url=base_url,
                token=token,
                user_id=user_id,
                message=user_input,
                conversation_id=conversation_id,
            )
            if conversation_id:
                print(f"(conversation_id={conversation_id})")


if __name__ == "__main__":
    main()
