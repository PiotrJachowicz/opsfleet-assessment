from pathlib import Path

from agent_eval.scoring import CaseResult, QualityResults, QuestionResult, STATUS_SCORED
from agent_eval.suite import EVAL_TRACE, load_suite


def test_load_suite_parses_cases_and_globals() -> None:
    path = Path(__file__).parent / "data" / "retail_agent_eval.yaml"
    suite = load_suite(path)
    assert len(suite.cases) >= 5
    assert suite.global_questions
    assert any(q.target == EVAL_TRACE for q in suite.global_questions)
    case = suite.cases[0]
    questions = suite.questions_for(case)
    assert len(questions) > len(case.evaluation_questions)
    brand_case = next(c for c in suite.cases if c.id == 7)
    assert brand_case.auth_preset == "calvin"
    assert brand_case.category == "brand_auth"
    assessment = [c for c in suite.cases if c.category == "assessment"]
    assert {c.id for c in assessment} == {8, 9, 10}


def test_suite_score_ignores_empty() -> None:
    results = QualityResults(
        cases=[
            CaseResult(
                case_id=1,
                category="analysis",
                question="q",
                status=STATUS_SCORED,
                questions=[
                    QuestionResult(question="a", passed=True, reason="ok"),
                    QuestionResult(question="b", passed=False, reason="no"),
                ],
            )
        ]
    )
    assert results.suite_score == 0.5
    assert results.passed_questions == 1
    assert results.total_questions == 2
