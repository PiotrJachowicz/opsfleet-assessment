from __future__ import annotations

from functools import lru_cache

from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

from chatbot.config import Settings, get_settings
from chatbot.integrations.bigquery import list_schema, run_sql
from chatbot.llm import create_chat_model
from chatbot.middleware import build_model_retry_middleware
from chatbot.reports import create_html_report, get_report, list_reports

SYSTEM_PROMPT = """
You are a retail data analysis assistant for non-technical executives.

You have BigQuery tools for the public thelook_ecommerce dataset.
For any question that needs numbers, trends, or comparisons:
1. Call list_schema if you need table/column details.
2. Write read-only SQL with fully-qualified table names.
3. Call run_sql.
4. Answer using only the query results. If a query fails, repair and retry.

You can also manage saved HTML report artifacts for the current user:
- create_html_report(title, body_html): save a styled report. Pass inner HTML only
  (use h2/p/ul/table). Call this when the user asks to create/save a report.
- list_reports(): list this user's saved reports.
- get_report(report_id): load one report owned by this user (HTML + path).

Never invent metrics. Prefer concise executive-friendly answers with key figures.
Prefer fewer, denser SQL queries over many small ones when summarizing the dataset.
""".strip()


@lru_cache
def get_analysis_agent() -> CompiledStateGraph:
    settings = get_settings()
    model = create_chat_model(settings)
    return create_agent(
        model=model,
        tools=[
            list_schema,
            run_sql,
            create_html_report,
            list_reports,
            get_report,
        ],
        system_prompt=SYSTEM_PROMPT,
        middleware=[build_model_retry_middleware(settings)],
        name="retail-analyst",
    )


def agent_config(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    return {"recursion_limit": settings.agent_recursion_limit}
