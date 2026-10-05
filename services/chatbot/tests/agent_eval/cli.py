"""CLI for the retail agent LLM-as-judge eval suite.

Env (optional):
  AGENT_BASE_URL       chatbot base URL          (default http://127.0.0.1:8000)
  EVAL_USER_ID         user_id sent to /chat     (default eval-runner)
  JUDGE_MODEL          Gemini judge model id     (default GEMINI_MODEL / gemini-3.8-flash)
  GEMINI_API_KEY       required for the judge
  EVAL_YAML            path to cases YAML
  EVAL_CASES           "all" | "1,3" | "1-4" | category name
  EVAL_DEMO            1 to run the single demo case (case 5 / tool_use)
  EVAL_CONCURRENCY     concurrent cases          (default 2; demo forces 1)
  EVAL_TIMEOUT         per-case timeout seconds  (default 300)
  EVAL_OUT             JSON results path         (default ./eval-results.json)
  EVAL_UPLOAD          1 to upload to LangSmith  (default 1 when LANGSMITH_API_KEY set)
  LANGSMITH_API_KEY    upload credentials
  LANGSMITH_ENDPOINT   optional API URL
  LANGSMITH_DATASET    dataset name              (default opsfleet-retail-agent-eval)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # tests/ -> agent_eval
sys.path.insert(0, str(_HERE.parents[2]))  # services/chatbot -> chatbot package

from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: E402

from agent_eval.client import ChatbotAgent  # noqa: E402
from agent_eval.judge import Judge  # noqa: E402
from agent_eval.langsmith_upload import upload_experiment  # noqa: E402
from agent_eval.runner import run_suite  # noqa: E402
from agent_eval.suite import Suite, load_suite  # noqa: E402
from chatbot.config import get_settings  # noqa: E402

_TRUTHY = {"1", "true", "yes", "on"}
# Light schema/tool case — good smoke demo under rate limits.
DEMO_CASE_ID = 5


def _select_case_ids(suite: Suite, spec: str) -> set[int] | None:
    spec = (spec or "").strip()
    if not spec or spec.lower() == "all":
        return None
    low = spec.lower()
    cat_match = {c.id for c in suite.cases if c.category.lower() == low}
    if cat_match:
        return cat_match
    ids: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            ids.update(range(int(lo), int(hi) + 1))
        elif part.isdigit():
            ids.add(int(part))
    return ids or None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in _TRUTHY


def write_results(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retail chatbot agent eval")
    parser.add_argument("--yaml", default=os.environ.get("EVAL_YAML") or "")
    parser.add_argument("--cases", default=os.environ.get("EVAL_CASES") or "all")
    parser.add_argument(
        "--demo",
        action="store_true",
        default=_env_bool("EVAL_DEMO"),
        help=f"Run only the demo case (id={DEMO_CASE_ID}, tool_use / list_schema)",
    )
    parser.add_argument(
        "--out",
        default=os.environ.get("EVAL_OUT") or str(_HERE.parent / "eval-results.json"),
    )
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args(argv)

    yaml_path = Path(
        args.yaml
        or (_HERE.parent / "data" / "retail_agent_eval.yaml")
    )
    suite = load_suite(yaml_path)
    settings = get_settings()

    if args.demo:
        case_ids = {DEMO_CASE_ID}
        cases_filter = f"demo:{DEMO_CASE_ID}"
        if not any(c.id == DEMO_CASE_ID for c in suite.cases):
            print(
                f"Demo case id={DEMO_CASE_ID} not found in {yaml_path}",
                file=sys.stderr,
            )
            return 2
    else:
        case_ids = _select_case_ids(suite, args.cases)
        cases_filter = args.cases

    selected = [c for c in suite.cases if case_ids is None or c.id in case_ids]
    base_url = os.environ.get("AGENT_BASE_URL") or "http://127.0.0.1:8000"
    concurrency = 1 if args.demo else int(os.environ.get("EVAL_CONCURRENCY") or 2)

    api_key = (os.environ.get("GEMINI_API_KEY") or settings.gemini_api_key or "").strip()
    if not api_key:
        print("GEMINI_API_KEY is required for the judge", file=sys.stderr)
        return 2

    judge_model_id = (
        os.environ.get("JUDGE_MODEL")
        or os.environ.get("GEMINI_MODEL")
        or settings.gemini_model
        or "gemini-3.8-flash"
    )

    ls_key = (
        os.environ.get("LANGSMITH_API_KEY") or settings.langsmith_api_key or ""
    ).strip()
    should_upload = (not args.no_upload) and _env_bool(
        "EVAL_UPLOAD",
        default=bool(ls_key),
    )

    print("=== Agent eval ===", flush=True)
    print(f"yaml:          {yaml_path}", flush=True)
    print(f"base_url:      {base_url}", flush=True)
    print(f"judge_model:   {judge_model_id}", flush=True)
    print(f"cases_filter:  {cases_filter}", flush=True)
    print(f"selected:      {', '.join(str(c.id) for c in selected) or '(none)'}", flush=True)
    print(f"concurrency:   {concurrency}", flush=True)
    print(f"langsmith_up:  {should_upload}", flush=True)
    print(flush=True)

    agent = ChatbotAgent(
        base_url=base_url,
        jwt_secret=settings.jwt_secret,
        timeout_s=float(os.environ.get("EVAL_TIMEOUT") or 300),
    )
    try:
        print(f"Health check {base_url}/health …", flush=True)
        agent.healthcheck()
        print("Health check OK", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Chatbot not reachable at {base_url}: {exc}", file=sys.stderr)
        return 2

    judge = Judge(
        ChatGoogleGenerativeAI(
            model=judge_model_id,
            api_key=api_key,
            vertexai=False,
            temperature=0,
        )
    )

    results = await run_suite(
        suite,
        agent,
        judge,
        case_ids=case_ids,
        concurrency=concurrency,
        judge_concurrency=1 if args.demo else int(os.environ.get("EVAL_JUDGE_CONCURRENCY") or 4),
    )
    print(flush=True)
    results.print_summary()

    payload: dict[str, Any] = results.to_dict()
    payload["meta"] = {
        "yaml": str(yaml_path),
        "base_url": base_url,
        "judge_model": judge_model_id,
        "cases_filter": cases_filter,
        "demo": bool(args.demo),
    }

    if should_upload:
        if not ls_key:
            print("EVAL_UPLOAD set but LANGSMITH_API_KEY is empty", file=sys.stderr)
            return 2
        print("Uploading results to LangSmith…", flush=True)
        upload_meta = upload_experiment(
            suite=suite,
            results=results,
            dataset_name=(
                os.environ.get("LANGSMITH_DATASET")
                or settings.langsmith_dataset
                or "opsfleet-retail-agent-eval"
            ),
            api_key=ls_key,
            api_url=(
                os.environ.get("LANGSMITH_ENDPOINT")
                or settings.langsmith_endpoint
                or ""
            ).strip()
            or None,
        )
        payload["langsmith"] = upload_meta
        print(
            f"LangSmith experiment uploaded: {upload_meta['experiment_name']} "
            f"(dataset={upload_meta['dataset_name']})",
            flush=True,
        )
    else:
        print("Skipping LangSmith upload", flush=True)

    out_path = Path(args.out)
    write_results(out_path, payload)
    print(f"Wrote {out_path}", flush=True)
    return 0 if not results.errored() else 1


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_amain(argv)))


if __name__ == "__main__":
    main()
