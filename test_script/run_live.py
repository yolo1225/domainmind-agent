from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import evaluate as evaluator


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "reports" / "evaluation" / "runs"
STAGE_LIMITS = {"smoke": 6, "regression": 15, "formal": 50}
PRIOR_STAGE = {"regression": "smoke", "formal": "regression"}
TERMINAL_STATUSES = {"completed", "failed", "revision_required", "waiting_human"}
PROFILE_LEARNERS = {
    "beginner": "learner_001",
    "intermediate": "learner_003",
    "advanced": "learner_002",
}


class ApiFailure(RuntimeError):
    pass


def _api_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 30,
) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ApiFailure(f"{method} {path} returned {exc.code}: {detail[:500]}") from exc
    except (URLError, TimeoutError) as exc:
        raise ApiFailure(f"{method} {path} failed: {exc}") from exc
    if envelope.get("error"):
        raise ApiFailure(f"{method} {path} returned API error: {envelope['error']}")
    return envelope.get("data")


def _prior_stage_exists(stage: str) -> bool:
    required = PRIOR_STAGE.get(stage)
    if required is None:
        return True
    for path in RUN_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("stage") == required and payload.get("valid") is True:
                return True
        except (OSError, json.JSONDecodeError):
            continue
    return False


def _poll_task(base_url: str, task_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task = _api_json(base_url, "GET", f"/generation-tasks/{task_id}")
        if task.get("status") in TERMINAL_STATUSES:
            return task
        time.sleep(1)
    raise ApiFailure(f"task {task_id} did not finish within {timeout_seconds}s")


def _final_review(runs: list[dict[str, Any]], resource_type: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for run in runs:
        if (run.get("input_summary") or {}).get("step") != "review_resource":
            continue
        for report in (run.get("output_summary") or {}).get("resource_reviews", []):
            if report.get("resource_type") == resource_type:
                candidates.append(report)
    return candidates[-1] if candidates else {}


def _review_channels(report: dict[str, Any]) -> list[dict[str, Any]]:
    recheck = (report.get("arbitration") or {}).get("recheck_scores") or {}
    if recheck:
        return [recheck.get("primary") or {}, recheck.get("secondary") or {}]
    return [report.get("primary_review") or {}, report.get("secondary_review") or {}]


def _observed_result(
    case: dict[str, Any],
    task: dict[str, Any],
    runs: list[dict[str, Any]],
    elapsed_ms: int,
) -> dict[str, Any]:
    report = _final_review(runs, str(case["resource_type"]))
    channels = _review_channels(report)
    model_runs = [run for run in runs if run.get("model_name")]
    all_live = bool(model_runs) and all(
        (run.get("output_summary") or {}).get("provider_mode") == "live"
        for run in model_runs
    )
    claim_support: dict[str, list[bool | None]] = {}
    evidence_ids: set[str] = set()
    unable: list[str] = []
    for channel in channels:
        evidence_ids.update(str(item) for item in channel.get("evidence_refs", []) if item)
        unable.extend(str(item) for item in channel.get("unable_to_determine", []) if item)
        for check in channel.get("fact_checks", []):
            claim = str(check.get("claim") or "").strip()
            if not claim:
                continue
            claim_support.setdefault(claim, []).append(check.get("supported"))
            evidence_ids.update(str(item) for item in check.get("source_ids", []) if item)
            if not check.get("determinable", True):
                unable.append(claim)

    unsupported = sum(1 for values in claim_support.values() if False in values)
    target_ids = {str(item) for item in case.get("target_core_knowledge_ids", [])}
    covered_ids = target_ids & evidence_ids
    resource = next(
        (
            item
            for item in task.get("resources", [])
            if item.get("resource_type") == case.get("resource_type")
        ),
        {},
    )
    decision = str(report.get("decision") or task.get("decision") or "failed")
    conclusion = {
        "manual_review_required": "conflict",
        "rejected": "failed",
        "completed": "passed",
    }.get(decision, decision)
    agent_latency: dict[str, int] = {}
    for run in runs:
        step = str((run.get("input_summary") or {}).get("step") or "")
        if not step or run.get("model_name"):
            continue
        agent_latency[step] = agent_latency.get(step, 0) + int(run.get("duration_ms") or 0)

    determinable = bool(report and claim_support and all_live and not unable)
    return {
        "generated_fact_count": len(claim_support),
        "hallucinated_fact_count": unsupported,
        "difficulty_matched": bool(
            resource.get("difficulty") == case.get("target_difficulty")
            and float(report.get("difficulty_match") or 0) >= 85
        ),
        "covered_core_knowledge_count": len(covered_ids),
        "target_core_knowledge_count": len(target_ids),
        "review_conclusion": conclusion,
        "profile_decision": "not_evaluated",
        "latency_ms": elapsed_ms,
        "agent_latency_ms": agent_latency,
        "determinable": determinable,
        "unable_to_determine": sorted(set(unable)),
        "provider_mode": "live" if all_live else "invalid",
        "model_calls": [
            {
                "model_name": run.get("model_name"),
                "duration_ms": run.get("duration_ms"),
                "tokens_input": run.get("tokens_input"),
                "tokens_output": run.get("tokens_output"),
            }
            for run in model_runs
        ],
    }


def run_case(base_url: str, case: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    profile_type = str((case.get("profile_snapshot") or {}).get("profile_type") or "beginner")
    learner_id = PROFILE_LEARNERS.get(profile_type, "learner_001")
    payload = {
        "learner_id": learner_id,
        "trigger_type": "initial_generation",
        "execution_mode": "auto",
        "domain_code": "ai_app_dev",
        "resource_types": [case["resource_type"]],
        "learning_goal": (
            f"评测案例 {case['case_id']}，目标知识点："
            + "、".join(case.get("target_core_knowledge_ids", []))
        ),
    }
    started = time.perf_counter()
    created = _api_json(base_url, "POST", "/generation-tasks", payload)
    task_id = str(created["task_id"])
    task = _poll_task(base_url, task_id, timeout_seconds)
    runs = _api_json(base_url, "GET", f"/generation-tasks/{task_id}/agent-runs")
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return {
        "case_id": case["case_id"],
        "task_id": task_id,
        "task_status": task.get("status"),
        "observed_result": _observed_result(case, task, runs, elapsed_ms),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real-model evaluation through the public API.")
    parser.add_argument("--stage", choices=tuple(STAGE_LIMITS), required=True)
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--xlsx", action="store_true")
    args = parser.parse_args()

    if not _prior_stage_exists(args.stage):
        raise SystemExit(f"run {PRIOR_STAGE[args.stage]} stage successfully before {args.stage}")
    health = _api_json(args.base_url, "GET", "/health/dependencies")
    if not health.get("ready_for_live_demo"):
        raise SystemExit("backend is not ready for live demo; check model configuration and fixture mode")

    cases, versions = evaluator.load_cases()
    selected = cases[: STAGE_LIMITS[args.stage]]
    run_id = datetime.now(UTC).strftime(f"live-{args.stage}-%Y%m%dT%H%M%SZ")
    results: list[dict[str, Any]] = []
    for case in selected:
        try:
            results.append(run_case(args.base_url, case, args.timeout_seconds))
        except Exception as exc:
            results.append(
                {
                    "case_id": case["case_id"],
                    "error": str(exc),
                    "observed_result": {"determinable": False, "unable_to_determine": [str(exc)]},
                }
            )
        print(f"[{len(results)}/{len(selected)}] {case['case_id']}", flush=True)

    valid = not any(
        not item.get("observed_result", {}).get("determinable") for item in results
    )
    run = {
        "run_id": run_id,
        "run_mode": "live",
        "stage": args.stage,
        "case_count": len(results),
        "valid": valid,
        "model_configuration": {
            "generation_model": health.get("generation_model", {}).get("model_name"),
            "primary_review_model": health.get("primary_review_model", {}).get("model_name"),
            "secondary_review_model": health.get("secondary_review_model", {}).get("model_name"),
            "fixture_enabled": health.get("fixture_enabled"),
        },
        "knowledge_base_versions": sorted(versions),
        "started_at": datetime.now(UTC).isoformat(),
        "results": results,
    }
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / f"{run_id}.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    merged = evaluator.merge_live_results(cases, run)
    summary = evaluator.evaluate(merged, versions, run_mode="live", run_metadata=run)
    evaluator.write_reports(summary, xlsx=args.xlsx)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not valid or (args.stage == "formal" and summary["status"] != "passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
