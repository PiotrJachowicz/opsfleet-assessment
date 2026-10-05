"""Run each case against the live agent, then judge every criterion."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from agent_eval.client import ChatbotAgent
from agent_eval.judge import VERDICT_JUDGE_ERROR, Judge
from agent_eval.scoring import (
    Q_STATUS_JUDGE_ERROR,
    Q_STATUS_SCORED,
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_SCORED,
    CaseResult,
    QualityResults,
    QuestionResult,
)
from agent_eval.suite import Case, EvalQuestion, Suite


def _log(msg: str) -> None:
    print(msg, flush=True)


async def run_suite(
    suite: Suite,
    agent: ChatbotAgent,
    judge: Judge,
    *,
    case_ids: set[int] | None = None,
    concurrency: int = 2,
    judge_concurrency: int = 4,
    log: Callable[[str], None] = _log,
) -> QualityResults:
    cases = [c for c in suite.cases if case_ids is None or c.id in case_ids]
    global_texts = {q.text for q in suite.global_questions}
    case_sem = asyncio.Semaphore(concurrency)
    judge_sem = asyncio.Semaphore(judge_concurrency)
    results = QualityResults()

    log(f"Running {len(cases)} case(s) (concurrency={concurrency})")
    for case in cases:
        n_q = len(suite.questions_for(case))
        flag = "" if case.runnable else " [pending/skip]"
        log(f"  plan case {case.id} [{case.category}] auth={case.auth_preset}{flag} — {n_q} criteria")
        log(f"    Q: {case.question}")

    async def judge_one(
        case: Case, run, q: EvalQuestion
    ) -> QuestionResult:
        origin = "global" if q.text in global_texts else "case"
        short = q.text if len(q.text) <= 80 else q.text[:80] + "…"
        log(f"  case {case.id}: judging [{origin}/{q.target}] {short}")
        async with judge_sem:
            verdict = await judge.judge(
                question=case.question,
                run=run,
                evaluation_question=q.text,
                eval_target=q.target,
            )
        status = (
            Q_STATUS_JUDGE_ERROR
            if verdict.status == VERDICT_JUDGE_ERROR
            else Q_STATUS_SCORED
        )
        if status == Q_STATUS_JUDGE_ERROR:
            mark = "?"
        else:
            mark = "Y" if verdict.passed else "N"
        log(f"  case {case.id}: {mark} — {verdict.reason}")
        return QuestionResult(
            question=q.text,
            passed=verdict.passed,
            reason=verdict.reason,
            eval_target=q.target,
            origin=origin,
            status=status,
        )

    async def run_one(case: Case) -> CaseResult:
        if not case.runnable:
            log(f"case {case.id}: skipped (runnable=false)")
            return CaseResult(
                case_id=case.id,
                category=case.category,
                question=case.question,
                status=STATUS_PENDING,
                detail="runnable: false",
            )

        async with case_sem:
            log(f"case {case.id}: invoking agent as preset={case.auth_preset}…")
            run = await asyncio.to_thread(
                agent.invoke,
                case.id,
                case.question,
                auth_preset=case.auth_preset,
            )
            tools = len(run.tool_calls)
            preview = (run.answer or run.error or "").replace("\n", " ")
            if len(preview) > 120:
                preview = preview[:120] + "…"
            log(
                f"case {case.id}: agent done in {run.latency_s:.1f}s "
                f"(tools={tools}, answer_chars={len(run.answer or '')})"
            )
            if preview:
                log(f"case {case.id}: preview: {preview}")

        if run.error and not run.answer:
            log(f"case {case.id}: ERROR {run.error}")
            return CaseResult(
                case_id=case.id,
                category=case.category,
                question=case.question,
                status=STATUS_ERROR,
                detail=run.error,
                run=run,
            )

        questions = suite.questions_for(case)
        log(f"case {case.id}: judging {len(questions)} criteria…")
        judged = await asyncio.gather(*(judge_one(case, run, q) for q in questions))
        result = CaseResult(
            case_id=case.id,
            category=case.category,
            question=case.question,
            status=STATUS_SCORED,
            questions=list(judged),
            run=run,
        )
        log(
            f"case {case.id}: done score={result.score:.2f} "
            f"({result.passed}/{result.total})"
        )
        return result

    case_results = await asyncio.gather(*(run_one(case) for case in cases))
    results.cases = sorted(case_results, key=lambda c: c.case_id)
    return results
