"""Upload eval suite examples and experiment scores to LangSmith."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent_eval.scoring import STATUS_SCORED, QualityResults
from agent_eval.suite import Suite

logger = logging.getLogger(__name__)


def _example_map(client: Any, dataset_id: Any) -> dict[str, Any]:
    return {
        str((ex.inputs or {}).get("case_id")): ex
        for ex in client.list_examples(dataset_id=dataset_id)
    }


def upload_experiment(
    *,
    suite: Suite,
    results: QualityResults,
    dataset_name: str,
    experiment_prefix: str = "retail-agent-eval",
    api_key: str | None = None,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Create/update a dataset from the YAML suite and log an experiment project."""
    from langsmith import Client

    client = Client(api_key=api_key or None, api_url=api_url or None)
    if client.has_dataset(dataset_name=dataset_name):
        dataset = client.read_dataset(dataset_name=dataset_name)
    else:
        dataset = client.create_dataset(
            dataset_name=dataset_name,
            description=str(suite.meta.get("app") or "Retail agent eval suite"),
        )

    for case in suite.cases:
        inputs = {
            "case_id": case.id,
            "category": case.category,
            "question": case.question,
        }
        outputs = {
            "evaluation_questions": [
                {"question": q.text, "eval": q.target}
                for q in case.evaluation_questions
            ]
        }
        examples = _example_map(client, dataset.id)
        existing = examples.get(str(case.id))
        if existing is not None:
            client.update_example(
                example_id=existing.id,
                inputs=inputs,
                outputs=outputs,
            )
        else:
            client.create_example(
                dataset_id=dataset.id,
                inputs=inputs,
                outputs=outputs,
            )

    examples = _example_map(client, dataset.id)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    project_name = f"{experiment_prefix}-{stamp}"
    project = client.create_project(
        project_name,
        reference_dataset_id=dataset.id,
        description=f"suite_score={results.suite_score:.3f}",
    )

    for case in results.cases:
        run_id = uuid4()
        outputs: dict[str, Any] = {
            "status": case.status,
            "score": case.score,
            "answer": case.run.answer if case.run else "",
            "tool_calls": [
                {"name": t.name, "status": t.status}
                for t in (case.run.tool_calls if case.run else [])
            ],
            "questions": [
                {
                    "question": q.question,
                    "passed": q.passed,
                    "reason": q.reason,
                    "status": q.status,
                }
                for q in case.questions
            ],
        }
        if case.run and case.run.error:
            outputs["error"] = case.run.error

        example = examples.get(str(case.case_id))
        client.create_run(
            id=run_id,
            name=f"case-{case.case_id}",
            run_type="chain",
            inputs={
                "case_id": case.case_id,
                "category": case.category,
                "question": case.question,
            },
            outputs=outputs,
            project_name=project_name,
            reference_example_id=example.id if example is not None else None,
        )

        if case.status == STATUS_SCORED:
            client.create_feedback(
                run_id=run_id,
                key="case_score",
                score=case.score,
                comment=f"{case.passed}/{case.total}",
            )
            for q in case.questions:
                client.create_feedback(
                    run_id=run_id,
                    key="criterion",
                    score=1.0 if q.passed else 0.0,
                    comment=f"[{q.origin}/{q.eval_target}] {q.question} — {q.reason}",
                )

    try:
        client.create_feedback(
            key="suite_score",
            score=results.suite_score,
            comment=f"{results.passed_questions}/{results.total_questions}",
            project_id=getattr(project, "id", None),
        )
    except Exception:  # noqa: BLE001 - suite-level feedback is best-effort
        logger.debug("suite_score feedback skipped", exc_info=True)

    logger.info(
        "Uploaded LangSmith experiment dataset=%s project=%s score=%.3f",
        dataset_name,
        project_name,
        results.suite_score,
    )
    return {
        "dataset_name": dataset_name,
        "dataset_id": str(dataset.id),
        "experiment_name": project_name,
        "suite_score": results.suite_score,
    }
