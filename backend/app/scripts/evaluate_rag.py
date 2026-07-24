from __future__ import annotations

import argparse
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agents.v2_retrieval_agent import V2KnowledgeRetrievalAgent
from app.rag.chunker import chunk_markdown
from app.rag.candidate_manifest import CandidateManifestStore
from app.rag.embeddings import embed_texts, embedding_model_name
from app.rag.vector_store import VectorStore
from app.scripts.validate_rag_evaluation import (
    DEFAULT_DATA_DIR,
    DEFAULT_KNOWLEDGE_PATH,
    load_evaluation_data,
    validate_rag_evaluation,
)
from app.scripts.validate_rag_seed import load_knowledge_items, source_data_version


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "rag_evaluation"
ALGORITHM_VERSION = "legacy-hash-baseline-1.0"
ENGINE_NAME = "legacy-hash"
V2_ENGINE_NAME = "v2-candidate"
V2_MODES = ("full", "semantic-only", "explicit-only", "semantic+relation")
TARGETS = {
    "recall_at_12": 0.90,
    "priority_top_12_coverage": 0.95,
    "prerequisite_coverage": 0.90,
    "source_completeness": 1.0,
    "cross_domain_errors": 0,
    "p95_latency_ms": 3000,
}


def _document_for(item: dict[str, Any], chunk: str) -> str:
    return (
        f"知识点：{item['name']}\n"
        f"分类：{item['category']}\n"
        f"难度：{item['difficulty']}\n"
        f"标签：{'、'.join(item.get('tags', []))}\n\n"
        f"{chunk}"
    )


def build_legacy_corpus(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    corpus: list[dict[str, Any]] = []
    documents: list[str] = []
    for item in sorted(items, key=lambda value: str(value["knowledge_id"])):
        chunks = chunk_markdown(str(item["content"]))
        for index, chunk in enumerate(chunks):
            document = _document_for(item, chunk)
            documents.append(document)
            corpus.append(
                {
                    "chunk_id": f"{item['knowledge_id']}::chunk::{index}",
                    "knowledge_id": item["knowledge_id"],
                    "domain_code": item["domain_code"],
                    "name": item["name"],
                    "source_title": item["source_title"],
                    "source_url": item.get("source_url"),
                    "license_note": item["license_note"],
                }
            )
    vectors = embed_texts(documents)
    for entry, vector in zip(corpus, vectors, strict=True):
        entry["embedding"] = vector
    return corpus


def _squared_l2(left: list[float], right: list[float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=True))


def legacy_hash_query(
    corpus: list[dict[str, Any]], query_text: str, *, n_results: int = 12
) -> list[dict[str, Any]]:
    query_embedding = embed_texts([query_text])[0]
    ranked = sorted(
        (
            (_squared_l2(query_embedding, entry["embedding"]), entry["chunk_id"], entry)
            for entry in corpus
        ),
        key=lambda value: (value[0], value[1]),
    )[:n_results]
    return [
        {
            key: value
            for key, value in entry.items()
            if key != "embedding"
        }
        | {
            "distance": round(distance, 8),
            "similarity": round(1 / (1 + distance), 8),
        }
        for distance, _, entry in ranked
    ]


def _ratio(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "ratio": round(numerator / denominator, 6) if denominator else None,
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 3)


def _deduplicate_knowledge(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for match in matches:
        knowledge_id = str(match["knowledge_id"])
        if knowledge_id in seen:
            continue
        seen.add(knowledge_id)
        unique.append(match)
    return unique


def evaluate_cases(
    cases: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    *,
    split: str,
    knowledge_ids: set[str],
    knowledge_version: str,
    acceptance_hash: str,
) -> dict[str, Any]:
    recall_numerator = recall_denominator = 0
    priority_numerator = priority_denominator = 0
    direct_numerator = direct_denominator = 0
    prerequisite_numerator = prerequisite_denominator = 0
    discovered_numerator = discovered_denominator = 0
    source_numerator = source_denominator = 0
    cross_domain_errors = 0
    latencies: list[float] = []
    results: list[dict[str, Any]] = []
    failed: dict[str, list[str]] = {
        "recall_at_12": [],
        "priority": [],
        "prerequisite": [],
        "discovered_prerequisite": [],
        "source_completeness": [],
        "cross_domain": [],
    }

    for case in cases:
        plan = case["retrieval_plan"]
        query_text = " ".join(str(term).strip() for term in plan["query_terms"] if str(term).strip())
        started = time.perf_counter()
        chunk_matches = legacy_hash_query(corpus, query_text, n_results=plan["n_results"])
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(elapsed_ms)
        matches = _deduplicate_knowledge(chunk_matches)
        retrieved_ids = [str(match["knowledge_id"]) for match in matches]
        retrieved_set = set(retrieved_ids)
        gold_ids = {str(label["knowledge_id"]) for label in case["gold_knowledge"]}
        priority_ids = set(plan["priority_knowledge_ids"])
        prerequisite_ids = set(plan["prerequisite_knowledge_ids"])
        discovered_ids = {
            str(label["knowledge_id"])
            for label in case["gold_knowledge"]
            if label["expected_route"] == "prerequisite" and label["input_role"] == "none"
        }

        recall_hit = len(gold_ids & retrieved_set)
        recall_numerator += recall_hit
        recall_denominator += len(gold_ids)
        priority_hit = len(priority_ids & retrieved_set)
        priority_numerator += priority_hit
        priority_denominator += len(priority_ids)
        direct_numerator += len(priority_ids & knowledge_ids)
        direct_denominator += len(priority_ids)
        prerequisite_hit = len(prerequisite_ids & retrieved_set)
        prerequisite_numerator += prerequisite_hit
        prerequisite_denominator += len(prerequisite_ids)
        discovered_hit = len(discovered_ids & retrieved_set)
        discovered_numerator += discovered_hit
        discovered_denominator += len(discovered_ids)

        complete_sources = 0
        for match in matches:
            source_denominator += 1
            if all(match.get(field) for field in ("source_title", "source_url", "license_note")):
                source_numerator += 1
                complete_sources += 1
            if match.get("domain_code") != "ai_app_dev":
                cross_domain_errors += 1
        case_failures: list[str] = []
        if recall_hit < len(gold_ids):
            failed["recall_at_12"].append(case["case_id"])
            case_failures.append("recall_at_12")
        if priority_hit < len(priority_ids):
            failed["priority"].append(case["case_id"])
            case_failures.append("priority")
        if prerequisite_hit < len(prerequisite_ids):
            failed["prerequisite"].append(case["case_id"])
            case_failures.append("prerequisite")
        if discovered_hit < len(discovered_ids):
            failed["discovered_prerequisite"].append(case["case_id"])
            case_failures.append("discovered_prerequisite")
        if complete_sources < len(matches):
            failed["source_completeness"].append(case["case_id"])
            case_failures.append("source_completeness")
        if any(match.get("domain_code") != "ai_app_dev" for match in matches):
            failed["cross_domain"].append(case["case_id"])
            case_failures.append("cross_domain")
        results.append(
            {
                "case_id": case["case_id"],
                "query_text": query_text,
                "latency_ms": round(elapsed_ms, 3),
                "gold_knowledge_ids": sorted(gold_ids),
                "retrieved_knowledge_ids": retrieved_ids,
                "failures": case_failures,
                "top_12": [
                    {
                        "rank": rank,
                        "chunk_id": match["chunk_id"],
                        "knowledge_id": match["knowledge_id"],
                        "distance": match["distance"],
                        "source_title": match["source_title"],
                        "source_url": match["source_url"],
                    }
                    for rank, match in enumerate(matches, 1)
                ],
            }
        )

    metrics = {
        "recall_at_12": _ratio(recall_numerator, recall_denominator),
        "priority_direct_availability": _ratio(direct_numerator, direct_denominator),
        "priority_top_12_coverage": _ratio(priority_numerator, priority_denominator),
        "explicit_prerequisite_coverage": _ratio(
            prerequisite_numerator, prerequisite_denominator
        ),
        "discovered_prerequisite_coverage": _ratio(discovered_numerator, discovered_denominator),
        "prerequisite_coverage": _ratio(
            prerequisite_numerator + discovered_numerator,
            prerequisite_denominator + discovered_denominator,
        ),
        "source_completeness": _ratio(source_numerator, source_denominator),
        "cross_domain_errors": cross_domain_errors,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "v2_contract_illegal_outputs": None,
    }
    target_checks = {
        "recall_at_12": (metrics["recall_at_12"]["ratio"] or 0) >= TARGETS["recall_at_12"],
        "priority_top_12_coverage": (
            metrics["priority_top_12_coverage"]["ratio"] or 0
        )
        >= TARGETS["priority_top_12_coverage"],
        "prerequisite_coverage": (metrics["prerequisite_coverage"]["ratio"] or 0)
        >= TARGETS["prerequisite_coverage"],
        "source_completeness": (metrics["source_completeness"]["ratio"] or 0)
        == TARGETS["source_completeness"],
        "cross_domain_errors": cross_domain_errors == TARGETS["cross_domain_errors"],
        "p95_latency_ms": (metrics["latency_ms"]["p95"] or math.inf)
        <= TARGETS["p95_latency_ms"],
    }
    return {
        "status": "baseline_recorded",
        "engine": ENGINE_NAME,
        "embedding_model": embedding_model_name(),
        "algorithm_version": ALGORITHM_VERSION,
        "split": split,
        "case_count": len(cases),
        "source_data_version": knowledge_version,
        "acceptance_cases_sha256": acceptance_hash,
        "metrics": metrics,
        "future_v2_target_checks": target_checks,
        "failed_case_ids": failed,
        "cases": results,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


def evaluate_v2_cases(
    cases: list[dict[str, Any]],
    agent: Any,
    *,
    split: str,
    knowledge_ids: set[str],
    knowledge_version: str,
    acceptance_hash: str,
    embedding_model: str,
    index_version: str,
    mode: str,
) -> dict[str, Any]:
    """Evaluate the frozen V2 contract without exposing any legacy retrieval path."""
    recall_numerator = recall_denominator = 0
    priority_numerator = priority_denominator = 0
    direct_numerator = direct_denominator = 0
    prerequisite_numerator = prerequisite_denominator = 0
    discovered_numerator = discovered_denominator = 0
    source_numerator = source_denominator = 0
    cross_domain_errors = contract_illegal_outputs = 0
    latencies: list[float] = []
    results: list[dict[str, Any]] = []
    failed: dict[str, list[str]] = {
        "recall_at_12": [],
        "priority": [],
        "prerequisite": [],
        "discovered_prerequisite": [],
        "source_completeness": [],
        "cross_domain": [],
        "contract": [],
    }

    from app.scripts.validate_rag_evaluation import materialize_retrieve_input

    for case in cases:
        contract_input = materialize_retrieve_input(case, "ai_app_dev")
        started = time.perf_counter()
        try:
            output = agent.execute(contract_input)
            output = output.model_validate(output.model_dump())
        except Exception as exc:
            contract_illegal_outputs += 1
            failed["contract"].append(case["case_id"])
            results.append(
                {
                    "case_id": case["case_id"],
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "failures": ["contract"],
                    "error_type": type(exc).__name__,
                }
            )
            continue
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(elapsed_ms)
        matches = _deduplicate_knowledge([chunk.model_dump() for chunk in output.chunks])
        retrieved_ids = [str(match["knowledge_id"]) for match in matches]
        retrieved_set = set(retrieved_ids)
        plan = case["retrieval_plan"]
        gold_ids = {str(label["knowledge_id"]) for label in case["gold_knowledge"]}
        priority_ids = set(plan["priority_knowledge_ids"])
        prerequisite_ids = set(plan["prerequisite_knowledge_ids"])
        discovered_ids = {
            str(label["knowledge_id"])
            for label in case["gold_knowledge"]
            if label["expected_route"] == "prerequisite" and label["input_role"] == "none"
        }
        recall_hit = len(gold_ids & retrieved_set)
        priority_hit = len(priority_ids & retrieved_set)
        prerequisite_hit = len(prerequisite_ids & retrieved_set)
        discovered_hit = len(discovered_ids & retrieved_set)
        recall_numerator += recall_hit
        recall_denominator += len(gold_ids)
        priority_numerator += priority_hit
        priority_denominator += len(priority_ids)
        direct_numerator += len(priority_ids & knowledge_ids)
        direct_denominator += len(priority_ids)
        prerequisite_numerator += prerequisite_hit
        prerequisite_denominator += len(prerequisite_ids)
        discovered_numerator += discovered_hit
        discovered_denominator += len(discovered_ids)
        case_failures: list[str] = []
        for match in matches:
            source_denominator += 1
            source = match["source"]
            if all(source.get(field) for field in ("source_title", "source_url", "license_note")):
                source_numerator += 1
            if match["knowledge_id"] not in knowledge_ids:
                cross_domain_errors += 1
        if recall_hit < len(gold_ids):
            failed["recall_at_12"].append(case["case_id"])
            case_failures.append("recall_at_12")
        if priority_hit < len(priority_ids):
            failed["priority"].append(case["case_id"])
            case_failures.append("priority")
        if prerequisite_hit < len(prerequisite_ids):
            failed["prerequisite"].append(case["case_id"])
            case_failures.append("prerequisite")
        if discovered_hit < len(discovered_ids):
            failed["discovered_prerequisite"].append(case["case_id"])
            case_failures.append("discovered_prerequisite")
        if any(not all(match["source"].get(field) for field in ("source_title", "source_url", "license_note")) for match in matches):
            failed["source_completeness"].append(case["case_id"])
            case_failures.append("source_completeness")
        if any(match["knowledge_id"] not in knowledge_ids for match in matches):
            failed["cross_domain"].append(case["case_id"])
            case_failures.append("cross_domain")
        results.append(
            {
                "case_id": case["case_id"],
                "query_text": output.query_text,
                "latency_ms": round(elapsed_ms, 3),
                "gold_knowledge_ids": sorted(gold_ids),
                "retrieved_knowledge_ids": retrieved_ids,
                "failures": case_failures,
                "top_12": [
                    {
                        "rank": rank,
                        "chunk_id": chunk.chunk_id,
                        "knowledge_id": chunk.knowledge_id,
                        "similarity": chunk.similarity,
                        "matched_by": chunk.matched_by.value,
                        "source_title": chunk.source.source_title,
                        "source_url": chunk.source.source_url,
                    }
                    for rank, chunk in enumerate(output.chunks, 1)
                ],
            }
        )
    metrics = {
        "recall_at_12": _ratio(recall_numerator, recall_denominator),
        "priority_direct_availability": _ratio(direct_numerator, direct_denominator),
        "priority_top_12_coverage": _ratio(priority_numerator, priority_denominator),
        "explicit_prerequisite_coverage": _ratio(prerequisite_numerator, prerequisite_denominator),
        "discovered_prerequisite_coverage": _ratio(discovered_numerator, discovered_denominator),
        "prerequisite_coverage": _ratio(
            prerequisite_numerator + discovered_numerator,
            prerequisite_denominator + discovered_denominator,
        ),
        "source_completeness": _ratio(source_numerator, source_denominator),
        "cross_domain_errors": cross_domain_errors,
        "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
        "v2_contract_illegal_outputs": contract_illegal_outputs,
    }
    target_checks = {
        "recall_at_12": (metrics["recall_at_12"]["ratio"] or 0) >= TARGETS["recall_at_12"],
        "priority_top_12_coverage": (metrics["priority_top_12_coverage"]["ratio"] or 0) >= TARGETS["priority_top_12_coverage"],
        "prerequisite_coverage": (metrics["prerequisite_coverage"]["ratio"] or 0) >= TARGETS["prerequisite_coverage"],
        "source_completeness": (metrics["source_completeness"]["ratio"] or 0) == TARGETS["source_completeness"],
        "cross_domain_errors": cross_domain_errors == TARGETS["cross_domain_errors"],
        "p95_latency_ms": (metrics["latency_ms"]["p95"] or math.inf) <= TARGETS["p95_latency_ms"],
        "v2_contract_illegal_outputs": contract_illegal_outputs == 0,
    }
    return {
        "status": "evaluated",
        "engine": V2_ENGINE_NAME,
        "mode": mode,
        "embedding_model": embedding_model,
        "algorithm_version": ALGORITHM_VERSION.replace("legacy-hash", "v2-candidate"),
        "index_version": index_version,
        "split": split,
        "case_count": len(cases),
        "source_data_version": knowledge_version,
        "acceptance_cases_sha256": acceptance_hash,
        "metrics": metrics,
        "target_checks": target_checks,
        "failed_case_ids": failed,
        "cases": results,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


def _markdown_report(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    lines = [
        "# RAG Legacy Hash Baseline",
        "",
        f"- 状态：{result['status']}",
        f"- 数据集：{result['split']}（{result['case_count']} 条）",
        f"- Embedding：{result['embedding_model']}",
        f"- 算法版本：{result['algorithm_version']}",
        f"- 知识数据版本：`{result['source_data_version']}`",
        f"- 冻结验收哈希：`{result['acceptance_cases_sha256']}`",
        f"- 评测时间：{result['evaluated_at']}",
        "",
        "| 指标 | 分子 | 分母 | 比率 | 后续 V2 目标 |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, target in (
        ("recall_at_12", ">= 90%"),
        ("priority_top_12_coverage", ">= 95%"),
        ("prerequisite_coverage", ">= 90%"),
        ("source_completeness", "= 100%"),
    ):
        value = metrics[key]
        lines.append(
            f"| {key} | {value['numerator']} | {value['denominator']} | "
            f"{value['ratio']} | {target} |"
        )
    lines.extend(
        [
            "",
            f"- 跨领域错误：{metrics['cross_domain_errors']}",
            f"- 延迟：P50 {metrics['latency_ms']['p50']} ms，P95 {metrics['latency_ms']['p95']} ms",
            "- V2 契约非法输出：不适用（本报告记录 V1 legacy-hash 输出）。",
            "",
            "> 本报告是旧哈希检索的对照基线。未达到未来 V2 门槛不代表本次数据切片失败。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(result: dict[str, Any], output_dir: Path = DEFAULT_REPORT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = (
        f"legacy-hash-baseline-v1-{result['split']}"
        if result["engine"] == ENGINE_NAME
        else f"v2-candidate-{result.get('mode', 'full')}-{result['split']}"
    )
    (output_dir / f"{stem}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / f"{stem}.md").write_text(_markdown_report(result), encoding="utf-8")


def run_evaluation(
    *,
    split: str,
    data_dir: Path = DEFAULT_DATA_DIR,
    knowledge_path: Path = DEFAULT_KNOWLEDGE_PATH,
) -> dict[str, Any]:
    validation = validate_rag_evaluation(data_dir, knowledge_path)
    datasets, _ = load_evaluation_data(data_dir)
    cases = (
        [*datasets["development"], *datasets["acceptance"]]
        if split == "all"
        else datasets[split]
    )
    items = load_knowledge_items(knowledge_path)
    return evaluate_cases(
        cases,
        build_legacy_corpus(items),
        split=split,
        knowledge_ids={str(item["knowledge_id"]) for item in items},
        knowledge_version=source_data_version(items),
        acceptance_hash=validation["acceptance_cases_sha256"],
    )


def run_v2_evaluation(
    *,
    split: str,
    mode: str,
    data_dir: Path = DEFAULT_DATA_DIR,
    knowledge_path: Path = DEFAULT_KNOWLEDGE_PATH,
) -> dict[str, Any]:
    validation = validate_rag_evaluation(data_dir, knowledge_path)
    datasets, _ = load_evaluation_data(data_dir)
    cases = [*datasets["development"], *datasets["acceptance"]] if split == "all" else datasets[split]
    items = load_knowledge_items(knowledge_path)
    client = VectorStore().client
    manifest = CandidateManifestStore().load(
        "ai_app_dev", collection_exists=lambda name: _candidate_collection_exists(client, name)
    )
    if manifest is None:
        raise RuntimeError("candidate manifest is missing")
    with V2KnowledgeRetrievalAgent.production(mode=mode) as agent:
        return evaluate_v2_cases(
            cases,
            agent,
            split=split,
            knowledge_ids={str(item["knowledge_id"]) for item in items},
            knowledge_version=source_data_version(items),
            acceptance_hash=validation["acceptance_cases_sha256"],
            embedding_model=manifest.embedding_model,
            index_version=manifest.index_version,
            mode=mode,
        )


def _candidate_collection_exists(client: Any, name: str) -> bool:
    try:
        client.get_collection(name=name)
    except Exception:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the dedicated RAG gold dataset.")
    parser.add_argument("--engine", choices=(ENGINE_NAME, V2_ENGINE_NAME), default=ENGINE_NAME)
    parser.add_argument("--mode", choices=V2_MODES, default="full")
    parser.add_argument("--live", action="store_true", help="Required for the paid V2 embedding path.")
    parser.add_argument("--split", choices=("development", "acceptance", "all"), required=True)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--knowledge-path", type=Path, default=DEFAULT_KNOWLEDGE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()
    if args.engine == V2_ENGINE_NAME and not args.live:
        parser.error("--live is required for v2-candidate; it never falls back to mock embeddings")
    result = (
        run_v2_evaluation(
            split=args.split, mode=args.mode, data_dir=args.data_dir, knowledge_path=args.knowledge_path
        )
        if args.engine == V2_ENGINE_NAME
        else run_evaluation(split=args.split, data_dir=args.data_dir, knowledge_path=args.knowledge_path)
    )
    if not args.no_write:
        write_report(result, args.output_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        metrics = result["metrics"]
        print(
            "RAG legacy hash baseline recorded: "
            f"split={args.split}, cases={result['case_count']}, "
            f"recall@12={metrics['recall_at_12']['ratio']}, "
            f"p95={metrics['latency_ms']['p95']}ms."
        )


if __name__ == "__main__":
    main()
