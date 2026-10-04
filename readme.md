# Retail Data Analysis Chatbot (prototype)

## Prerequisites

- [mise](https://mise.jdx.dev/)
- [Docker](https://docs.docker.com/get-docker/)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)

## Setup

```bash
mise install
mise trust
cp services/chatbot/.env.example services/chatbot/.env
```

Put your key in `services/chatbot/.env` as `GEMINI_API_KEY=...`.

## Run

```bash
mise run chatbot-setup
mise run dev
```

`mise run dev` starts Postgres (`infra:up`), applies migrations, then runs the chatbot with reload.

Postgres is published on host port **5433** (to avoid clashing with a local 5432 Postgres).

## Smoke check

```bash
curl http://127.0.0.1:8000/health
curl -N http://127.0.0.1:8000/hello
```

## CLI

With the server running (`mise run dev` in another terminal):

```bash
mise run chat
```

Interactive REPL: type messages, stream replies, `/new` starts a fresh conversation, `/quit` exits.

When the model returns thought summaries, the CLI prints a `Thinking>` section before `Assistant>`.

Optional env (in `services/chatbot/.env`): `CHAT_BASE_URL`, `CHAT_USER_ID`, `GEMINI_INCLUDE_THOUGHTS`, `GEMINI_THINKING_LEVEL` (`minimal` / `low` / `medium` / `high`).

## Chat (SSE / curl)

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H 'content-type: application/json' \
  -d '{"user_id":"demo","message":"Say hi in one sentence"}'
```

Reuse the `conversation_id` from the `meta` event for multiturn follow-ups.

## Infra only

```bash
mise run infra:up
mise run infra:down
```
