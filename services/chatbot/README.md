# Chatbot service

Starlette backend for the retail data analysis chatbot prototype.

See the repository root `readme.md` for setup and run instructions.

## Auth

`POST /chat` requires `Authorization: Bearer <jwt>` (HS256, `JWT_SECRET`).
Claims: `sub` (user id), `brands` (`["*"]` for admin, or concrete brand names).

Brand scope is enforced in SQL for `products` and `order_items` (see
`chatbot/integrations/bigquery/brand_scope.py`). Prompt-only trust is not used.

## Reports

HTML reports are stored under `REPORTS_DIR` (default `output/reports`) with rows
in the `reports` table. Tools: `create_html_report`, `list_reports`, `get_report`,
`propose_delete_report` (always filtered by the JWT `sub`).

Deletion is two-step: the model may only *propose* a delete. The next user
message is inspected by the server for an exact `y`; only then is the report
removed. Production should replace this chat `y` gate with a UI confirmation
flow — documented in the root `readme.md`.

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
