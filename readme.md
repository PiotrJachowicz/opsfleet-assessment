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

LangSmith is optional — see [LangSmith (optional)](#langsmith-optional) below.
Leave `LANGSMITH_*` empty to run without traces.

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

Interactive REPL: type messages, stream replies, `/new` starts a fresh conversation,
`/user <admin|calvin|levis>` switches preset identity, `/quit` exits.

The agent can call BigQuery tools (`list_schema`, `run_sql`). The CLI shows:

- `Tool>` for tool start/end
- `Thinking>` for model thought summaries
- `Assistant>` for the final answer tokens

Try: `What were the top 5 product brands by revenue last year?`

## Auth (JWT brand scopes)

Brand/product access is enforced in SQL (not only in the prompt): filters are
injected into `products` and `order_items` queries before BigQuery runs.

Allowed brands come from the JWT `brands` claim — **the same shape as the HLD**.
There is no user→brand lookup in Postgres. A richer mapping is an HLD future
consideration. The CLI mints HS256 JWTs for three presets (shared `JWT_SECRET`
must match between `apps/chat-cli/.env` and `services/chatbot/.env`):

| Preset | Scopes |
|--------|--------|
| `admin` | all brands (`*`) |
| `calvin` | `Calvin Klein` only |
| `levis` | `Levi's` only |

The HLD uses the client's identity JWT with the same `brands` claim. The
prototype only differs in who mints the token (CLI presets vs the client's IdP).

## Saved reports

The agent can create styled HTML report artifacts via tools:

- `create_html_report` — writes `output/reports/*.html` and a per-user DB row;
  pass `mentioned_clients` when the report names clients/brands (stored lowercased)
- `list_reports` / `get_report` — scoped to the authenticated JWT user; list can
  filter by `this_conversation`, `conversation_id`, or `mentioned_client`
- `propose_delete_report` — stages a single delete; **does not delete**
- `propose_delete_reports` — stages a bulk delete by conversation and/or
  mentioned client tag; **does not delete**

**Deletion confirmation (prototype vs production):** In production, destructive
report deletes would use a proper UI confirmation (modal / HITL interrupt) so the
model never holds the delete trigger. In this prototype, after
`propose_delete_report` / `propose_delete_reports` the user must reply with exactly
`y` (lowercase, alone). The **chat server** checks that string in application code
and only then deletes the file(s) + DB row(s). The model has no delete tool and
cannot confirm deletion itself. Any other reply cancels the pending delete.

`output/` is gitignored (reports under `output/reports`, logs under `output/logs`).
Run migrations after pull (`mise run migrate`).

## Metrics

`GET /metrics` exposes Prometheus counters/histograms (turn latency/errors, tool
ok/error, BigQuery outcomes, Gemini retries, report delete lifecycle, auth
failures). Implementation: `services/chatbot/chatbot/middleware/metrics.py`.

## Application logs

Prototype logging uses Python’s stdlib ``logging`` with a rotating **file sink**
at `services/chatbot/output/logs/chatbot.log` (configurable via `LOGS_DIR` /
`LOG_FILE_NAME`). That path is for local debugging only.

In production (see `docs/HLD.md`), the same log calls target **GCP Cloud Logging**
via the **Cloud Logging handler** — no application call-site changes.

CLI env: `CHAT_BASE_URL`, `CHAT_USER_PRESET`, `JWT_SECRET`.

Service env: `GEMINI_*`, `JWT_SECRET`, `GCP_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS`, optional `LANGSMITH_*`, etc.

Transient Gemini `429` / `503` responses are retried with exponential backoff (and server `retryDelay` when present).

## LangSmith (optional)

LangSmith is **optional**. Chat, BigQuery tools, and the CLI work with no
LangSmith config — traces and eval uploads are simply skipped.

To collect traces, add to `services/chatbot/.env`:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=opsfleet-chatbot
```

Optional: `LANGSMITH_ENDPOINT` (self-hosted / EU), `LANGSMITH_DATASET` (eval
dataset name, default `opsfleet-retail-agent-eval`).

Get an API key from [LangSmith](https://smith.langchain.com/). Email/phone are
scrubbed from traced payloads via the shared PII helper.

If `LANGSMITH_TRACING` is unset/false, or the API key is missing, the service
starts normally and does not send traces.

## Agent evals (LLM-as-judge)

With the chatbot already running:

```bash
mise run eval:demo   # one light case (recommended under rate limits)
mise run eval        # full suite
```

This runs the YAML suite in `services/chatbot/tests/agent_eval/`, writes
`eval-results.json`, and uploads a LangSmith dataset/experiment **only when**
`LANGSMITH_API_KEY` is set (pass `--no-upload` / `EVAL_UPLOAD=0` to force skip).
Without LangSmith, evals still run and write the local JSON report. See
`services/chatbot/tests/agent_eval/README.md`.

**Judge note:** the prototype defaults the judge to Gemini (same key as the agent) because the assessment stack is Gemini-oriented. The HLD judge is **ChatGPT 5.1 sol** (different family from the Gemini agent).

## Chat (SSE / curl)

`POST /chat` requires `Authorization: Bearer <jwt>`. Mint a token with the same
`JWT_SECRET` as the service (CLI does this for presets), then:

```bash
TOKEN=$(cd apps/chat-cli && uv run python -c "from chat_cli.auth import mint_access_token; from chat_cli.config import get_settings; print(mint_access_token(preset_key='calvin', secret=get_settings().jwt_secret))")

curl -N -X POST http://127.0.0.1:8000/chat \
  -H 'content-type: application/json' \
  -H "authorization: Bearer $TOKEN" \
  -d '{"message":"Top brands by revenue?"}'
```

Reuse the `conversation_id` from the `meta` event for multiturn follow-ups.

## Infra only

```bash
mise run infra:up
mise run infra:down
```
