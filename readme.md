# Retail Data Analysis Chatbot (prototype)

## Prerequisites

- [mise](https://mise.jdx.dev/)
- [Docker](https://docs.docker.com/get-docker/)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)
- Google Cloud auth for BigQuery public datasets

## Setup

```bash
mise install
mise trust
cp services/chatbot/.env.example services/chatbot/.env
cp apps/chat-cli/.env.example apps/chat-cli/.env
```

Put your key in `services/chatbot/.env` as `GEMINI_API_KEY=...`.

### BigQuery auth

Either:

```bash
gcloud auth application-default login
gcloud config set project ops-test-piotr
```

Or set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json` and `GCP_PROJECT=...` in `.env`.

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
```

## CLI

With the server running (`mise run dev` in another terminal):

```bash
mise run chat-cli-setup
mise run chat
```

Interactive REPL: type messages, stream replies, `/new` starts a fresh conversation, `/quit` exits.

The agent can call BigQuery tools (`list_schema`, `run_sql`). The CLI shows:

- `Tool>` for tool start/end
- `Thinking>` for model thought summaries
- `Assistant>` for the final answer tokens

Try: `What were the top 5 product brands by revenue last year?`

CLI env (in `apps/chat-cli/.env`): `CHAT_BASE_URL`, `CHAT_USER_ID`.

Service env (in `services/chatbot/.env`): `GEMINI_*`, `GCP_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS`, etc.

Transient Gemini `429` / `503` responses are retried with exponential backoff (and server `retryDelay` when present).

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
