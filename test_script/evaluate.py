from __future__ import annotations

import argparse
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "data" / "evaluation_cases"
REPORT_DIR = ROOT / "reports" / "evaluation"
SCRIPT_VERSION = "live-evaluator-2.0"


def load_cases() -> tuple[list[dict[str, Any]], set[str]]:
    cases: list[dict[str, Any]] = []
    versions: set[str] = set()
    for path in sorted(CASES_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        file_cases = payload.get("cases", []) if isinstance(payload, dict) else payload
        if not isinstance(file_cases, list):
            raise ValueError(f"{path.name}: cases must be an array")
        cases.extend(file_cases)
        if isinstance(payload, dict) and payload.get("knowledge_base_version"):
            versions.add(str(payload["knowledge_base_version"]))
    case_ids = [str(item.get("case_id")) for item in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate case_id found")
    return cases, versions


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "ratio": round(numerator / denominator, 4) if denominator else None,
    }


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    values = sorted(values)
    index = max(0, min(len(values) - 1, int((len(values) - 1) * percentile + 0.9999)))
    return values[index]


def load_live_run(run_id: str | None) -> dict[str, Any]:
    run_dir = REPORT_DIR / "runs"
    if run_id:
        path = run_dir / f"{run_id}.json"
    else:
        candidates = sorted(run_dir.glob("*.json"), key=lambda item: item.stat().st_mtime)
        if not candidates:
            raise FileNotFoundError("no live evaluation run found")
        path = candidates[-1]
    if not path.is_file():
        raise FileNotFoundError(f"live evaluation run not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def merge_live_results(
    cases: list[dict[str, Any]], run: dict[str, Any]
) -> list[dict[str, Any]]:
    by_case = {str(item["case_id"]): item for item in run.get("results", [])}
    merged: list[dict[str, Any]] = []
    for source in cases:
        case_id = str(source.get("case_id"))
        if case_id not in by_case:
            continue
        item = copy.deepcopy(source)
        item["observed_result"] = by_case[case_id].get("observed_result", {})
        merged.append(item)
    return merged


def evaluate(
    cases: list[dict[str, Any]],
    knowledge_versions: set[str],
    *,
    run_mode: str = "baseline",
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_metadata = run_metadata or {}
    determinable = [item for item in cases if item.get("observed_result", {}).get("determinable")]
    undetermined = [str(item.get("case_id")) for item in cases if item not in determinable]
    facts = sum(int(item["observed_result"].get("generated_fact_count", 0)) for item in determinable)
    hallucinated = sum(
        int(item["observed_result"].get("hallucinated_fact_count", 0)) for item in determinable
    )
    difficulty_pass = [
        str(item["case_id"])
        for item in determinable
        if bool(item["observed_result"].get("difficulty_matched"))
    ]
    coverage_numerator = sum(
        int(item["observed_result"].get("covered_core_knowledge_count", 0))
        for item in determinable
    )
    coverage_denominator = sum(
        int(item["observed_result"].get("target_core_knowledge_count", 0))
        for item in determinable
    )
    review_pass = [
        str(item["case_id"])
        for item in determinable
        if item["observed_result"].get("review_conclusion")
        == item.get("expected_review_conclusion")
    ]
    profile_pass = [
        str(item["case_id"])
        for item in determinable
        if item["observed_result"].get("profile_decision")
        == item.get("expected_profile_decision")
    ]
    latencies = [
        int(item["observed_result"].get("latency_ms", 0))
        for item in determinable
        if item["observed_result"].get("latency_ms") is not None
    ]
    agent_latency_values: dict[str, list[int]] = {}
    for item in determinable:
        for agent_name, duration in (
            item["observed_result"].get("agent_latency_ms") or {}
        ).items():
            agent_latency_values.setdefault(agent_name, []).append(int(duration))
    difficulty = _ratio(len(difficulty_pass), len(determinable))
    coverage = _ratio(coverage_numerator, coverage_denominator)
    hallucination = _ratio(hallucinated, facts)
    result = {
        "status": "passed"
        if len(cases) >= 50
        and hallucination["ratio"] is not None
        and hallucination["ratio"] < 0.05
        and difficulty["ratio"] is not None
        and difficulty["ratio"] >= 0.85
        and coverage["ratio"] is not None
        and coverage["ratio"] >= 0.90
        else "failed",
        "case_count": len(cases),
        "mvp_target_case_count": 50,
        "evaluated_case_count": len(determinable),
        "metrics": {
            "hallucination_rate": hallucination,
            "difficulty_match_accuracy": difficulty,
            "core_knowledge_coverage": coverage,
            "review_decision_accuracy": _ratio(len(review_pass), len(determinable)),
            "profile_decision_accuracy": _ratio(len(profile_pass), len(determinable)),
            "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
            "agent_latency_ms": {
                name: {"p50": _percentile(values, 0.50), "p95": _percentile(values, 0.95)}
                for name, values in sorted(agent_latency_values.items())
            },
        },
        "failed_case_ids": {
            "hallucination": [
                str(item["case_id"])
                for item in determinable
                if int(item["observed_result"].get("hallucinated_fact_count", 0)) > 0
            ],
            "difficulty": [str(item["case_id"]) for item in determinable if str(item["case_id"]) not in difficulty_pass],
            "coverage": [
                str(item["case_id"])
                for item in determinable
                if int(item["observed_result"].get("covered_core_knowledge_count", 0))
                < int(item["observed_result"].get("target_core_knowledge_count", 0))
            ],
            "review_decision": [str(item["case_id"]) for item in determinable if str(item["case_id"]) not in review_pass],
            "profile_decision": [str(item["case_id"]) for item in determinable if str(item["case_id"]) not in profile_pass],
        },
        "unable_to_determine": {
            "count": len(undetermined),
            "case_ids": undetermined,
            "statement": "Cases without a determinable observed result are excluded from metric denominators.",
        },
        "knowledge_base_versions": sorted(knowledge_versions),
        "run_mode": run_mode,
        "run_id": run_metadata.get("run_id"),
        "stage": run_metadata.get("stage"),
        "model_configuration": run_metadata.get("model_configuration", {}),
        "script_version": SCRIPT_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
    return result


def write_reports(result: dict[str, Any], *, xlsx: bool) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    mode = result.get("run_mode", "baseline")
    stem = "latest-live" if mode == "live" else "latest-baseline"
    (REPORT_DIR / f"{stem}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if mode == "baseline":
        (REPORT_DIR / "latest.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    metrics = result["metrics"]
    lines = [
        f"# {mode.upper()} 可复现评测报告",
        "",
        f"- 状态：{result['status']}",
        f"- 案例：{result['evaluated_case_count']}/{result['case_count']}",
        f"- 知识库版本：{', '.join(result['knowledge_base_versions'])}",
        f"- 脚本版本：{result['script_version']}",
        f"- 评测时间：{result['evaluated_at']}",
        f"- 运行模式：{mode}",
        f"- 运行编号：{result.get('run_id') or 'baseline'}",
        "",
        "| 指标 | 分子 | 分母 | 比率 |",
        "|---|---:|---:|---:|",
    ]
    for label, key in (
        ("幻觉率", "hallucination_rate"),
        ("难度匹配准确率", "difficulty_match_accuracy"),
        ("核心知识覆盖率", "core_knowledge_coverage"),
        ("审核结论准确率", "review_decision_accuracy"),
        ("画像结论准确率", "profile_decision_accuracy"),
    ):
        item = metrics[key]
        lines.append(f"| {label} | {item['numerator']} | {item['denominator']} | {item['ratio']} |")
    lines.extend(
        [
            "",
            f"性能：P50 {metrics['latency_ms']['p50']} ms，P95 {metrics['latency_ms']['p95']} ms。",
            "",
            "## 失败案例",
            "",
            *[
                f"- {name}: {', '.join(ids) if ids else '无'}"
                for name, ids in result["failed_case_ids"].items()
            ],
            "",
            f"无法判定：{result['unable_to_determine']['statement']}",
        ]
    )
    agent_latency = metrics.get("agent_latency_ms") or {}
    if agent_latency:
        lines.extend(["", "## Agent 性能", "", "| Agent | P50 ms | P95 ms |", "|---|---:|---:|"])
        for name, values in agent_latency.items():
            lines.append(f"| {name} | {values['p50']} | {values['p95']} |")
    (REPORT_DIR / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if mode == "baseline":
        (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if xlsx:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "summary"
        sheet.append(["metric", "numerator", "denominator", "ratio"])
        for key, item in metrics.items():
            if isinstance(item, dict) and "ratio" in item:
                sheet.append([key, item["numerator"], item["denominator"], item["ratio"]])
        sheet.append(["latency_p50_ms", metrics["latency_ms"]["p50"], None, None])
        sheet.append(["latency_p95_ms", metrics["latency_ms"]["p95"], None, None])
        agent_sheet = workbook.create_sheet("agent_latency")
        agent_sheet.append(["agent", "p50_ms", "p95_ms"])
        for name, values in metrics.get("agent_latency_ms", {}).items():
            agent_sheet.append([name, values["p50"], values["p95"]])
        workbook.save(REPORT_DIR / f"{stem}.xlsx")
        if mode == "baseline":
            workbook.save(REPORT_DIR / "latest.xlsx")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", action="store_true", help="also export latest.xlsx")
    parser.add_argument("--mode", choices=("baseline", "live"), default="baseline")
    parser.add_argument("--run-id", help="live run id; latest run is used when omitted")
    args = parser.parse_args()
    cases, versions = load_cases()
    run: dict[str, Any] = {}
    if args.mode == "live":
        run = load_live_run(args.run_id)
        cases = merge_live_results(cases, run)
    result = evaluate(cases, versions, run_mode=args.mode, run_metadata=run)
    write_reports(result, xlsx=args.xlsx)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
