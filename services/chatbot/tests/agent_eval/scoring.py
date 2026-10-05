"""Deterministic scoring over binary judge verdicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_eval.client import AgentRun

STATUS_SCORED = "scored"
STATUS_ERROR = "error"
STATUS_PENDING = "pending"

Q_STATUS_SCORED = "scored"
Q_STATUS_JUDGE_ERROR = "judge_error"


@dataclass
class QuestionResult:
    question: str
    passed: bool
    reason: str
    eval_target: str = "answer"
    origin: str = "case"
    status: str = Q_STATUS_SCORED


@dataclass
class CaseResult:
    case_id: int
    category: str
    question: str
    status: str
    detail: str = ""
    questions: list[QuestionResult] = field(default_factory=list)
    run: AgentRun | None = None

    @property
    def total(self) -> int:
        return sum(1 for q in self.questions if q.status == Q_STATUS_SCORED)

    @property
    def passed(self) -> int:
        return sum(1 for q in self.questions if q.status == Q_STATUS_SCORED and q.passed)

    @property
    def judge_errors(self) -> int:
        return sum(1 for q in self.questions if q.status == Q_STATUS_JUDGE_ERROR)

    @property
    def score(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass
class QualityResults:
    cases: list[CaseResult] = field(default_factory=list)

    def scored(self) -> list[CaseResult]:
        return [c for c in self.cases if c.status == STATUS_SCORED]

    def errored(self) -> list[CaseResult]:
        return [c for c in self.cases if c.status == STATUS_ERROR]

    def pending(self) -> list[CaseResult]:
        return [c for c in self.cases if c.status == STATUS_PENDING]

    @property
    def total_questions(self) -> int:
        return sum(c.total for c in self.scored())

    @property
    def passed_questions(self) -> int:
        return sum(c.passed for c in self.scored())

    @property
    def suite_score(self) -> float:
        return (
            self.passed_questions / self.total_questions if self.total_questions else 0.0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_score": self.suite_score,
            "passed_questions": self.passed_questions,
            "total_questions": self.total_questions,
            "scored_cases": len(self.scored()),
            "error_cases": len(self.errored()),
            "pending_cases": len(self.pending()),
            "cases": [
                {
                    "case_id": c.case_id,
                    "category": c.category,
                    "question": c.question,
                    "status": c.status,
                    "detail": c.detail,
                    "score": c.score,
                    "passed": c.passed,
                    "total": c.total,
                    "judge_errors": c.judge_errors,
                    "latency_s": c.run.latency_s if c.run else None,
                    "answer": c.run.answer if c.run else "",
                    "error": c.run.error if c.run else c.detail,
                    "tool_calls": [
                        {
                            "name": t.name,
                            "status": t.status,
                            "detail": t.detail,
                        }
                        for t in (c.run.tool_calls if c.run else [])
                    ],
                    "questions": [
                        {
                            "question": q.question,
                            "passed": q.passed,
                            "reason": q.reason,
                            "eval_target": q.eval_target,
                            "origin": q.origin,
                            "status": q.status,
                        }
                        for q in c.questions
                    ],
                }
                for c in self.cases
            ],
        }

    def print_summary(self) -> None:
        print(
            f"suite_score={self.suite_score:.3f} "
            f"({self.passed_questions}/{self.total_questions}) "
            f"scored={len(self.scored())} error={len(self.errored())} "
            f"pending={len(self.pending())}"
        )
        for case in self.cases:
            mark = {
                STATUS_SCORED: "PASS" if case.score == 1.0 else "FAIL",
                STATUS_ERROR: "ERR",
                STATUS_PENDING: "PEND",
            }.get(case.status, case.status)
            print(
                f"  [{mark}] case {case.case_id} ({case.category}) "
                f"score={case.score:.2f} {case.passed}/{case.total}"
            )
            for q in case.questions:
                if q.status == Q_STATUS_JUDGE_ERROR:
                    print(f"    ? {q.question} — {q.reason}")
                else:
                    print(f"    {'Y' if q.passed else 'N'} {q.question} — {q.reason}")
