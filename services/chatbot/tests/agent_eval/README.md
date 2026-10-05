# Agent quality eval suite (LLM-as-judge)

YAML cases live in `data/retail_agent_eval.yaml`. The runner hits the **live**
chatbot (`POST /chat` SSE), captures the answer + tool events, then scores each
yes/no criterion with a judge model. Results are written to JSON and, when
LangSmith credentials are present, uploaded as a dataset + experiment.

## Prerequisites

1. Chatbot running (`mise run dev`) with Gemini + BigQuery auth configured.
2. `GEMINI_API_KEY` available to the eval process (same `.env` as the service).
3. Optional: `LANGSMITH_API_KEY` for experiment upload (evals still run locally without it).

## Run

```bash
# single demo case (recommended under rate limits)
mise run eval:demo

# full suite
mise run eval
```

Or directly:

```bash
cd services/chatbot
uv run python tests/agent_eval/cli.py --demo
uv run python tests/agent_eval/cli.py
```

Useful filters:

```bash
EVAL_CASES=pii mise run eval
EVAL_CASES=1,4 EVAL_UPLOAD=0 uv run python tests/agent_eval/cli.py
```

`--demo` / `mise run eval:demo` runs only case **5** (schema / tool_use) with
concurrency 1 — enough to prove the harness without burning Gemini quota.

Case **7** (`brand_auth`, `auth_preset: calvin`) checks that a Calvin Klein–scoped
JWT only surfaces that brand in answers/tool results. Run it with
`EVAL_CASES=7` or `EVAL_CASES=brand_auth`.

## Judge model

Default judge is the same Gemini family as the agent (`JUDGE_MODEL` /
`GEMINI_MODEL`). That matches the prototype's Gemini-only constraint.

**Recommendation for production:** use a **different model family** for the
judge (prefer ChatGPT; Claude is also fine). Different families have different
strengths, so a cross-family judge is less likely to exhibit confirmation bias
when scoring work produced by the agent model. Documented in the HLD as well.

## LangSmith

- Live chat tracing: set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` on the
  service. Traced payloads are scrubbed for email/phone via the shared PII helper.
  Without these, the chatbot runs normally and gathers no traces.
- Eval upload: after a suite run, examples are upserted into
  `LANGSMITH_DATASET` (default `opsfleet-retail-agent-eval`) and scores are
  logged under a timestamped experiment project when `LANGSMITH_API_KEY` is set.
  Pass `--no-upload` or `EVAL_UPLOAD=0` to skip. Local `eval-results.json` is
  always written either way.
