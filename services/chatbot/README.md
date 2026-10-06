# Chatbot service

Starlette backend for the retail data analysis chatbot prototype.

See the repository root `readme.md` for setup and run instructions.

## Auth

`POST /chat` requires `Authorization: Bearer <jwt>` (HS256, `JWT_SECRET`).
Claims: `sub` (user id), `brands` (`["*"]` for admin, or concrete brand names).

Brand scope is enforced in SQL for `products` and `order_items` (see
`chatbot/integrations/bigquery/brand_scope.py`). Prompt-only trust is not used.

**Prototype simplification:** scopes come from the JWT `brands` claim only — no
Postgres entitlement-mapping lookup. Production (HLD) resolves entitlements from
the DB after auth, then applies the same SQL rewriter.

## Reports

HTML reports are stored under `REPORTS_DIR` (default `output/reports`) with rows
in the `reports` table. Tools: `create_html_report` (optional `mentioned_clients`
tags), filtered `list_reports`, `get_report`, `propose_delete_report`, and
`propose_delete_reports` for bulk filters (`this_conversation` /
`conversation_id` / `mentioned_client`). Always scoped to the JWT `sub`.

Deletion is two-step: the model may only *propose* a delete (single or bulk).
The next user message is inspected by the server for an exact `y`; only then are
matching reports removed. Production should replace this chat `y` gate with a UI
confirmation flow — documented in the root `readme.md`.

## Metrics

Prometheus metrics live in `chatbot/middleware/metrics.py` and are scraped at
`GET /metrics`.

| Metric | Labels | Meaning |
|--------|--------|---------|
| `chatbot_chat_turns_total` | `status` | Turn completions (`ok` / `error` / `cancelled`) |
| `chatbot_chat_turn_duration_seconds` | — | Turn latency histogram |
| `chatbot_tool_calls_total` | `tool`, `status` | Tool ok/error rate |
| `chatbot_bq_queries_total` | `outcome` | `ok` / `empty` / `empty_exhausted` / `sql_rejected` / `bq_error` |
| `chatbot_model_retries_total` | `result` | Gemini `retry` / `exhausted` |
| `chatbot_report_deletes_total` | `outcome` | `proposed` / `confirmed` / `cancelled` / `error` |
| `chatbot_auth_failures_total` | — | Invalid JWT |

LangSmith remains the deep-dive trace store; these counters are for dashboards/alerts.

## Empty / failed SQL repair

`run_sql` detects zero-row results and SQL/BQ failures in application code and
returns a structured `status` / `repair_required` payload. Empty results are
budgeted per chat turn (`BQ_EMPTY_REPAIR_ATTEMPTS`, default 2) so the agent can
self-correct without unbounded BigQuery spend.

## Logging

Uses the standard library ``logging`` package (no extra dependency). Bootstrap
lives in `chatbot/observability/` alongside LangSmith tracing setup.

- **Prototype sink:** rotating file at `LOGS_DIR` / `LOG_FILE_NAME` (default
  `output/logs/chatbot.log`), plus console via uvicorn. `output/` is gitignored.
- **Production (HLD):** same logger API; swap the file sink for **GCP Cloud Logging**
  (Cloud Run stdout / Cloud Logging handler). Call sites do not change.

Useful fields logged: auth failures, chat turn start/done, tool start/end,
delete confirm/cancel, turn errors. Message bodies are not written to logs.

## LangSmith (optional)

No LangSmith config is required for local chat. Leave these unset (or
`LANGSMITH_TRACING=false`) and the service runs without sending traces.

To enable tracing, set in `.env`:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=opsfleet-chatbot
```

Traced payloads are scrubbed for email/phone. If tracing is on but the key is
missing, startup continues and tracing stays off.

## Evals

```bash
# server must be up (mise run dev)
mise run eval:demo   # one light case
mise run eval        # full suite
```

Local JSON results always write. LangSmith experiment upload happens only when
`LANGSMITH_API_KEY` is present. Details: `tests/agent_eval/README.md`.
