"""Load the ground-truth eval suite from YAML into typed cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EVAL_ANSWER = "answer"
EVAL_TRACE = "trace"
_EVAL_TARGETS = {EVAL_ANSWER, EVAL_TRACE}


@dataclass(frozen=True)
class EvalQuestion:
    text: str
    target: str = EVAL_ANSWER


@dataclass(frozen=True)
class Case:
    id: int
    category: str
    question: str
    evaluation_questions: list[EvalQuestion]
    runnable: bool = True
    # Preset JWT identity used when invoking the live agent (admin|calvin|levis).
    auth_preset: str = "admin"


@dataclass(frozen=True)
class Suite:
    meta: dict[str, Any]
    cases: list[Case]
    global_questions: list[EvalQuestion] = field(default_factory=list)

    def questions_for(self, case: Case) -> list[EvalQuestion]:
        return [*case.evaluation_questions, *self.global_questions]


def _parse_questions(raw: Any) -> list[EvalQuestion]:
    out: list[EvalQuestion] = []
    for item in raw or []:
        if isinstance(item, str):
            text, target = item.strip(), EVAL_ANSWER
        elif isinstance(item, dict):
            text = str(item.get("question") or "").strip()
            target = str(item.get("eval") or EVAL_ANSWER).strip().lower()
        else:
            continue
        if not text:
            continue
        if target not in _EVAL_TARGETS:
            raise ValueError(
                f"eval target must be one of {_EVAL_TARGETS}, got {target!r} for: {text}"
            )
        out.append(EvalQuestion(text=text, target=target))
    return out


def load_suite(path: str | Path) -> Suite:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    meta = data.get("meta", {}) or {}
    global_questions = _parse_questions(meta.get("global_evaluation_questions"))

    cases: list[Case] = []
    for raw in data.get("cases", []) or []:
        runnable_raw = raw.get("runnable", True)
        if isinstance(runnable_raw, str):
            runnable = runnable_raw.strip().lower() in {"1", "true", "yes", "on"}
        else:
            runnable = bool(runnable_raw)
        cases.append(
            Case(
                id=int(raw["id"]),
                category=str(raw.get("category") or "general"),
                question=str(raw["question"]).strip(),
                evaluation_questions=_parse_questions(raw.get("evaluation_questions")),
                runnable=runnable,
                auth_preset=str(raw.get("auth_preset") or "admin").strip() or "admin",
            )
        )
    return Suite(meta=meta, cases=cases, global_questions=global_questions)
