# Agent notes — OpsFleet retail analysis chatbot

Production design: `docs/HLD.md` and `docs/ArchitectureOverviewMermaid.md`.
Prototype setup/run: root `readme.md`. Brief: `instructions.md`.

## Layout

```
apps/chat-cli/          Interactive SSE client (JWT presets)
services/chatbot/       Starlette + LangGraph agent
  chatbot/              App code (not services/chatbot/src)
    integrations/bigquery/   Prototype SQL (thelook)
    reports/            HTML artifacts + confirm-delete
    middleware/         PII stream, retries, Prometheus
    observability/      Logging file sink + LangSmith
tests/agent_eval/       Live HTTP/SSE LLM-as-judge suite
mise/tasks/             `dev`, `chat`, `eval`, `eval:demo`, `migrate`
```

Use `mise` + `uv`. Postgres is on host **5433**. Do not invent a second package tree.

## Prototype vs HLD

| Topic | Prototype | Production (HLD) |
| --- | --- | --- |
| Analytics | BigQuery `thelook_ecommerce` | Client-provided **read-only SQL** store |
| Entitlements | JWT `brands` claim only | Postgres user→brand mapping |
| Delete confirm | Chat `y` gate in app code | HITL UI + HTTP hard-delete; agent has no delete tool |
| Logs | `output/logs` (gitignored) | Cloud Logging (same logger API) |
| Ingress | Direct `/chat` | BFF only |

Do not write BigQuery / `thelook_ecommerce` into HLD as the production warehouse.

## Coding conventions

- **Table FQNs** live in `chatbot/integrations/bigquery/tables.py`. Use those constants in sql_guard, brand_scope, schema catalog, and tests — never hardcode dataset table names.
- **`bigquery/__init__.py` must not import tools** (circular import with `config`).
- **PII**: email/phone via `chatbot.pii` (`EMAIL MASKED` / `PHONE MASKED`). Sanitize streams, tools, reports, traces.
- **Brand scope**: rewrite SQL in `brand_scope.py` for `products` and `order_items`. Do not rely on the prompt.
- **SQL**: read-only allowlist + empty-result / reject payloads from `run_sql` (`repair_required`, bounded `BQ_EMPTY_REPAIR_ATTEMPTS`).
- **Reports**: `create_html_report` with `mentioned_clients` tags. Delete only via `propose_delete_report` / `propose_delete_reports`; server deletes on exact `y`. No delete tool.
- **Tools**: put signatures and usage in **tool docstrings**. System prompt holds **policy** (when to save a report, never claim delete before `y`, SQL repair), not a duplicate tool catalog.
- **Observability**: `chatbot/observability/` for logging/tracing; counters in `middleware/metrics.py` (`GET /metrics`). Log ids (`user_id`, `conversation_id`, tool names), not message bodies.
- **Agent cache**: `get_analysis_agent` is lru-cached; bump recursion via `AGENT_RECURSION_LIMIT` (default 50). Restart the server after env changes.
- Prefer small unit tests for deterministic paths (SQL guard, PII, delete `y`, metrics, brand rewrite).

## Evals (required for features and bugfixes)

Live suite: `services/chatbot/tests/agent_eval/`. Cases: `data/retail_agent_eval.yaml`.

When you add or change user-visible agent behavior (tools, safety, reports, SQL repair, auth scope), **add or extend an eval case** in the same change:

1. New `id` (next integer) + `category`.
2. `question` or multi-turn `turns:`.
3. `evaluation_questions`: each is a yes/no where **yes = correct**. Use `eval: trace` for tool/SQL evidence; default is final answer.
4. Note the case in `tests/agent_eval/README.md`.
5. Run it: `EVAL_CASES=<id> mise run eval` (server must be up). Prefer `EVAL_CONCURRENCY=1` and **`mise run chatbot`** (no `--reload`) so SSE is not killed mid-turn.

```bash
mise run eval:demo              # case 5, cheap smoke
EVAL_CASES=7,8,9 mise run eval  # filter by id
EVAL_CASES=report_delete mise run eval
EVAL_UPLOAD=0 …                 # skip LangSmith
```

Existing categories worth matching: `analysis`, `sql`, `pii`, `tool_use`, `brand_auth`, `assessment`, `report_delete`, `report_delete_bulk`, `empty_result_repair`, `scope_policy`.

CLI exits **1** if any case is `error` (SSE drop, recursion limit), not merely a judge `[FAIL]`.

## Don’t

- Commit `.env` or keys.
- Give the model a tool that actually deletes reports.
- Skip evals for “small” agent behavior changes.
- Fix HLD as if the prototype warehouse were production BigQuery.
