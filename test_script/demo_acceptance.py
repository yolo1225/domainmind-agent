from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from run_live import _api_json, _poll_task


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "demo"


def _create_task(base_url: str, *, goal: str, resource_types: list[str]) -> dict[str, Any]:
    created = _api_json(
        base_url,
        "POST",
        "/generation-tasks",
        {
            "learner_id": "learner_001",
            "trigger_type": "initial_generation",
            "execution_mode": "auto",
            "learning_goal": goal,
            "resource_types": resource_types,
        },
    )
    return _poll_task(base_url, str(created["task_id"]), 360)


def _live_runs(base_url: str, task_id: str) -> list[dict[str, Any]]:
    runs = _api_json(base_url, "GET", f"/generation-tasks/{task_id}/agent-runs")
    model_runs = [run for run in runs if run.get("model_name")]
    if not model_runs or any(
        (run.get("output_summary") or {}).get("provider_mode") != "live" for run in model_runs
    ):
        raise AssertionError(f"task {task_id} does not contain exclusively live model calls")
    return runs


def _current_resource(base_url: str, resource_type: str = "lecture") -> dict[str, Any]:
    resources = _api_json(base_url, "GET", "/resources")
    resource = next(
        (item for item in resources if item.get("resource_type") == resource_type), None
    )
    if resource is None:
        raise AssertionError(f"no current passed {resource_type} resource found")
    return resource


def _profile_updated(runs: list[dict[str, Any]]) -> bool:
    return any(
        (run.get("input_summary") or {}).get("step") == "analyze_profile"
        and bool((run.get("output_summary") or {}).get("profile_update_required"))
        for run in runs
    )


def _load_snapshot(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    for branch in ("revision_exhausted", "manual_review_resume"):
        item = payload.get(branch)
        if item is None:
            continue
        required = {"task_id", "recorded_at", "model_names", "provider_mode"}
        if not required.issubset(item) or item["provider_mode"] != "live":
            raise ValueError(f"snapshot branch {branch} is missing live-run evidence")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the seven Docker demo acceptance branches.")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--snapshot", type=Path, help="optional real-run snapshot for branches 6/7")
    args = parser.parse_args()

    health = _api_json(args.base_url, "GET", "/health/dependencies")
    if not health.get("ready_for_live_demo"):
        raise SystemExit("real model channels are not ready or fixture mode is enabled")
    snapshots = _load_snapshot(args.snapshot)
    context: dict[str, Any] = {}
    branches: list[dict[str, Any]] = []

    def run_branch(branch_id: str, title: str, action: Callable[[], dict[str, Any]]) -> None:
        try:
            evidence = action()
            branches.append({"branch_id": branch_id, "title": title, "status": "passed", **evidence})
        except Exception as exc:
            snapshot = snapshots.get(branch_id)
            if snapshot:
                branches.append(
                    {
                        "branch_id": branch_id,
                        "title": title,
                        "status": "passed_from_live_snapshot",
                        "live_snapshot": snapshot,
                        "live_attempt_error": str(exc),
                    }
                )
            else:
                branches.append(
                    {"branch_id": branch_id, "title": title, "status": "failed", "error": str(exc)}
                )

    def initial_generation() -> dict[str, Any]:
        task = _create_task(
            args.base_url,
            goal="生成可追溯的个性化讲义、实操指南和分阶测验",
            resource_types=["lecture", "practice_guide", "graded_quiz"],
        )
        _live_runs(args.base_url, task["task_id"])
        if task["status"] != "completed" or len(task.get("resources", [])) != 3:
            raise AssertionError(f"initial task did not publish three resources: {task}")
        resource = _current_resource(args.base_url)
        context["resource_id"] = resource["resource_id"]
        return {"task_id": task["task_id"], "resource_count": 3}

    def no_change_explanation() -> dict[str, Any]:
        session = _api_json(
            args.base_url,
            "POST",
            "/tutoring/sessions",
            {"learner_id": "learner_001", "resource_id": context["resource_id"]},
        )
        response = _api_json(
            args.base_url,
            "POST",
            f"/tutoring/sessions/{session['session_id']}/messages",
            {"content": "这部分太难了，我第一次没有看懂。"},
        )
        if response.get("recommended_action") != "no_change" or response.get("task_id"):
            raise AssertionError(f"first subjective feedback must not change profile: {response}")
        context["session_id"] = session["session_id"]
        return {"session_id": session["session_id"], "decision": "no_change"}

    def evidence_profile_update() -> dict[str, Any]:
        response = _api_json(
            args.base_url,
            "POST",
            f"/tutoring/sessions/{context['session_id']}/messages",
            {
                "content": "我按提示重做后仍然答错，需要更基础的解释。",
                "evidence": [
                    {
                        "type": "scored_quiz",
                        "knowledge_id": "rag_pipeline_overview",
                        "score": 0,
                        "confidence": 0.95,
                    }
                ],
            },
        )
        task_id = response.get("task_id")
        if not task_id:
            raise AssertionError(f"second evidence-supported message did not create task: {response}")
        _poll_task(args.base_url, task_id, 360)
        runs = _live_runs(args.base_url, task_id)
        if not _profile_updated(runs):
            raise AssertionError("profile update was not recorded by analyze_profile")
        return {"task_id": task_id, "profile_update": True}

    def incorrect_review() -> dict[str, Any]:
        resource = _current_resource(args.base_url)
        response = _api_json(
            args.base_url,
            "POST",
            f"/resources/{resource['resource_id']}/feedback",
            {
                "learner_id": "learner_001",
                "feedback_type": "incorrect",
                "selected_text": "这一处事实与来源不一致，请复核。",
            },
        )
        task_id = response.get("task_id")
        if not task_id:
            raise AssertionError("incorrect feedback did not create a review task")
        _poll_task(args.base_url, task_id, 360)
        _live_runs(args.base_url, task_id)
        return {"task_id": task_id, "recommended_action": response["recommended_action"]}

    def challenge_task() -> dict[str, Any]:
        resource = _current_resource(args.base_url)
        session = _api_json(
            args.base_url,
            "POST",
            "/tutoring/sessions",
            {"learner_id": "learner_001", "resource_id": resource["resource_id"]},
        )
        response = _api_json(
            args.base_url,
            "POST",
            f"/tutoring/sessions/{session['session_id']}/messages",
            {"content": "这部分太简单了，我已经掌握，请给我更难的迁移挑战。"},
        )
        task_id = response.get("task_id")
        if response.get("recommended_action") != "challenge" or not task_id:
            raise AssertionError(f"challenge message did not create task: {response}")
        _poll_task(args.base_url, task_id, 360)
        _live_runs(args.base_url, task_id)
        return {"task_id": task_id, "recommended_action": "challenge"}

    def revision_exhausted() -> dict[str, Any]:
        task = _create_task(
            args.base_url,
            goal="仅依据检索来源生成；若无法满足全部来源、难度和覆盖要求则请求修订",
            resource_types=["lecture"],
        )
        _live_runs(args.base_url, task["task_id"])
        if int(task.get("revision_count") or 0) < 2 or task.get("status") != "failed":
            raise AssertionError("live models did not naturally reproduce two-revision exhaustion")
        return {"task_id": task["task_id"], "revision_count": task["revision_count"]}

    def manual_review_resume() -> dict[str, Any]:
        task = _create_task(
            args.base_url,
            goal="对存在证据边界争议的内容进行独立双模型审核",
            resource_types=["lecture"],
        )
        _live_runs(args.base_url, task["task_id"])
        if task.get("status") != "waiting_human":
            raise AssertionError("live review models did not naturally produce a persistent disagreement")
        reviews = _api_json(args.base_url, "GET", "/manual-reviews?status=pending")
        review = next((item for item in reviews if item.get("task_id") == task["task_id"]), None)
        if review is None:
            raise AssertionError("waiting task has no pending manual review")
        resolution = _api_json(
            args.base_url,
            "POST",
            f"/manual-reviews/{review['manual_review_id']}/decision",
            {"decision": "approve", "comment": "验收：人工核对来源后批准。"},
        )
        if resolution.get("resume_thread_id") != task["task_id"]:
            raise AssertionError("manual review did not resume the original thread")
        deadline = time.monotonic() + 360
        resumed: dict[str, Any] = {}
        while time.monotonic() < deadline:
            resumed = _api_json(
                args.base_url, "GET", f"/generation-tasks/{task['task_id']}"
            )
            if resumed.get("status") != "waiting_human" and resumed.get("status") in {
                "completed",
                "failed",
                "revision_required",
            }:
                break
            time.sleep(1)
        else:
            raise AssertionError("manual review resume did not reach a new terminal state")
        return {"task_id": task["task_id"], "resumed_status": resumed["status"]}

    run_branch("initial_generation", "首次生成三类资源", initial_generation)
    run_branch("no_change", "证据不足，仅解释且画像不变", no_change_explanation)
    run_branch("profile_update", "多轮证据创建画像新版本", evidence_profile_update)
    run_branch("incorrect_review", "错误反馈触发资源复核", incorrect_review)
    run_branch("challenge", "掌握后生成挑战任务", challenge_task)
    run_branch("revision_exhausted", "两轮自动修订后失败", revision_exhausted)
    run_branch("manual_review_resume", "双模型冲突与人工恢复", manual_review_resume)

    report = {
        "status": "passed" if all(item["status"].startswith("passed") for item in branches) else "failed",
        "provider_mode": "live",
        "model_configuration": {
            "generation_model": health["generation_model"]["model_name"],
            "primary_review_model": health["primary_review_model"]["model_name"],
            "secondary_review_model": health["secondary_review_model"]["model_name"],
        },
        "evaluated_at": datetime.now(UTC).isoformat(),
        "branches": branches,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# Docker 七分支演示验收", "", f"状态：{report['status']}", ""]
    lines.extend(
        f"- {item['title']}：{item['status']}（{item.get('task_id') or item.get('error', '')}）"
        for item in branches
    )
    (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
