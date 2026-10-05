"""Binary LLM-as-judge: one yes/no criterion per call."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from agent_eval.client import AgentRun
from agent_eval.suite import EVAL_TRACE

JUDGE_SYSTEM = """\
You are a strict evaluator for a retail data analysis chatbot that answers
executive questions by calling BigQuery tools (list_schema, run_sql) and writing
a concise evidence-based answer.

You are given:
  1. The user's original request.
  2. The agent's OUTPUT — either the final answer only, or the full execution
     trace (tool calls with args/results) plus the answer.
  3. ONE evaluation criterion, written as a yes/no question where "yes" ALWAYS
     means the agent did the correct thing.

Decide whether the output satisfies that one criterion.
  - passed = true ONLY if the output clearly satisfies it from the evidence shown.
  - passed = false if wrong, missing, hedged without answering, or unverifiable.
Judge only this criterion. Never output a numeric score.
"""

VERDICT_OK = "ok"
VERDICT_JUDGE_ERROR = "judge_error"
JUDGE_RETRY_BACKOFF: tuple[float, ...] = (2.0, 5.0)


class _VerdictModel(BaseModel):
    passed: bool = Field(description="true iff THIS criterion is satisfied")
    reason: str = Field(description="one concise sentence citing evidence")


@dataclass
class Verdict:
    passed: bool
    reason: str
    status: str = VERDICT_OK


def _render_trace(run: AgentRun) -> str:
    lines = ["TOOL TRACE:"]
    if not run.tool_calls:
        lines.append("(no tool calls)")
    for i, call in enumerate(run.tool_calls, start=1):
        lines.append(f"{i}. {call.name} [{call.status}] {call.detail[:800]}")
    lines.append("")
    lines.append("FINAL ANSWER:")
    lines.append(run.answer or "(empty)")
    return "\n".join(lines)


def _render_answer(run: AgentRun) -> str:
    return run.answer or "(empty)"


class Judge:
    def __init__(self, model: ChatGoogleGenerativeAI) -> None:
        self._model = model.with_structured_output(_VerdictModel)

    async def judge(
        self,
        *,
        question: str,
        run: AgentRun,
        evaluation_question: str,
        eval_target: str,
    ) -> Verdict:
        output = _render_trace(run) if eval_target == EVAL_TRACE else _render_answer(run)
        human = (
            f"USER REQUEST:\n{question}\n\n"
            f"AGENT OUTPUT:\n{output}\n\n"
            f"CRITERION (yes means correct):\n{evaluation_question}"
        )
        messages = [SystemMessage(content=JUDGE_SYSTEM), HumanMessage(content=human)]

        last_exc: Exception | None = None
        for attempt, delay in enumerate((0.0, *JUDGE_RETRY_BACKOFF)):
            if delay:
                await asyncio.sleep(delay)
            try:
                result = await self._model.ainvoke(messages)
                if isinstance(result, _VerdictModel):
                    return Verdict(passed=result.passed, reason=result.reason)
                return Verdict(
                    passed=bool(getattr(result, "passed", False)),
                    reason=str(getattr(result, "reason", "")),
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        return Verdict(
            passed=False,
            reason=f"judge failed after retries: {last_exc}",
            status=VERDICT_JUDGE_ERROR,
        )
