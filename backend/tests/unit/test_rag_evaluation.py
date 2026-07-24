from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.scripts.evaluate_rag import (
    build_legacy_corpus,
    evaluate_v2_cases,
    legacy_hash_query,
    run_evaluation,
)
from app.agents.contracts import RetrieveKnowledgeOutput, RetrievedChunk, RetrievalMatchType, RetrievalPurpose, SourceRef
from app.scripts.validate_rag_evaluation import (
    DEFAULT_DATA_DIR,
    DEFAULT_KNOWLEDGE_PATH,
    RagEvaluationValidationError,
    canonical_cases_sha256,
    load_evaluation_data,
    materialize_retrieve_input,
    validate_rag_evaluation,
)
from app.scripts.validate_rag_seed import load_knowledge_items


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _copy_dataset(tmp_path: Path) -> Path:
    target = tmp_path / "rag_evaluation"
    shutil.copytree(DEFAULT_DATA_DIR, target)
    return target


def test_rag_gold_dataset_is_valid_and_complete() -> None:
    result = validate_rag_evaluation()

    assert result["status"] == "passed"
    assert result["total_case_count"] == 50
    assert result["covered_knowledge_count"] == 50
    assert result["splits"]["development"]["case_count"] == 30
    assert result["splits"]["acceptance"]["case_count"] == 20
    assert result["splits"]["development"]["hidden_answer_cases"] >= 12
    assert result["splits"]["acceptance"]["hidden_answer_cases"] >= 8


def test_all_cases_materialize_as_frozen_retrieval_inputs() -> None:
    datasets, metadata = load_evaluation_data()

    for cases in datasets.values():
        for case in cases:
            contract = materialize_retrieve_input(case, "ai_app_dev")
            assert contract.task_id == case["case_id"]
            assert contract.context.domain_code == "ai_app_dev"
            assert contract.retrieval_plan.n_results == 12
    assert metadata["manifest"]["acceptance_case_count"] == 20


def test_acceptance_content_change_breaks_frozen_hash(tmp_path: Path) -> None:
    data_dir = _copy_dataset(tmp_path)
    path = data_dir / "acceptance_cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cases"][0]["query"] += "（已篡改）"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(RagEvaluationValidationError, match="frozen acceptance content hash"):
        validate_rag_evaluation(data_dir)


def test_hidden_gold_cannot_leak_into_explicit_input(tmp_path: Path) -> None:
    data_dir = _copy_dataset(tmp_path)
    path = data_dir / "development_cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    case = next(
        item
        for item in payload["cases"]
        if any(label["input_role"] == "none" for label in item["gold_knowledge"])
    )
    hidden = next(
        label["knowledge_id"]
        for label in case["gold_knowledge"]
        if label["input_role"] == "none"
    )
    case["retrieval_plan"]["priority_knowledge_ids"].append(hidden)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(RagEvaluationValidationError, match="hidden gold leaked"):
        validate_rag_evaluation(data_dir)


def test_canonical_case_hash_does_not_depend_on_file_order() -> None:
    datasets, _ = load_evaluation_data()
    cases = datasets["acceptance"]

    assert canonical_cases_sha256(cases) == canonical_cases_sha256(list(reversed(cases)))


def test_legacy_hash_ranking_is_deterministic() -> None:
    corpus = build_legacy_corpus(load_knowledge_items(DEFAULT_KNOWLEDGE_PATH))

    first = legacy_hash_query(corpus, "RAG 文档切片 标题 重叠上下文", n_results=12)
    second = legacy_hash_query(corpus, "RAG 文档切片 标题 重叠上下文", n_results=12)

    assert [item["chunk_id"] for item in first] == [item["chunk_id"] for item in second]
    assert [item["distance"] for item in first] == [item["distance"] for item in second]


def test_legacy_hash_evaluation_outcomes_are_deterministic() -> None:
    first = run_evaluation(split="acceptance")
    second = run_evaluation(split="acceptance")

    assert first["metrics"]["recall_at_12"] == second["metrics"]["recall_at_12"]
    assert first["metrics"]["priority_top_12_coverage"] == second["metrics"][
        "priority_top_12_coverage"
    ]
    assert [case["retrieved_knowledge_ids"] for case in first["cases"]] == [
        case["retrieved_knowledge_ids"] for case in second["cases"]
    ]


def test_rag_dataset_is_isolated_from_existing_p0_loader_directory() -> None:
    p0_path = PROJECT_ROOT / "data" / "evaluation_cases" / "p0_cases.json"
    p0_payload = json.loads(p0_path.read_text(encoding="utf-8"))
    loaded_p0_cases = []
    for path in sorted(p0_path.parent.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        loaded_p0_cases.extend(payload.get("cases", payload))

    assert len(p0_payload["cases"]) == 50
    assert len(loaded_p0_cases) == 50
    assert DEFAULT_DATA_DIR.parent != p0_path.parent


def test_v2_evaluation_records_contract_and_index_metadata() -> None:
    datasets, metadata = load_evaluation_data()
    case = next(
        item for item in datasets["development"] if item["retrieval_plan"]["priority_knowledge_ids"]
    )
    knowledge_id = case["retrieval_plan"]["priority_knowledge_ids"][0]

    class StubV2Agent:
        def execute(self, request):
            return RetrieveKnowledgeOutput(
                task_id=request.task_id,
                query_text="validated V2 query",
                chunks=[
                    RetrievedChunk(
                        chunk_id=f"{knowledge_id}::chunk::0",
                        knowledge_id=knowledge_id,
                        name="Knowledge",
                        category="RAG",
                        difficulty=2,
                        content="Traceable evidence",
                        similarity=0.75,
                        matched_by=RetrievalMatchType.PRIORITY,
                        used_for=RetrievalPurpose.REMEDIAL_EXPLANATION,
                        source=SourceRef(
                            source_ref_id=f"{knowledge_id}::chunk::0",
                            knowledge_id=knowledge_id,
                            source_title="Official source",
                            source_url="https://example.com/source",
                            license_note="Official documentation",
                        ),
                    )
                ],
                covered_knowledge_ids=[knowledge_id],
            )

    items = load_knowledge_items(DEFAULT_KNOWLEDGE_PATH)
    result = evaluate_v2_cases(
        [case],
        StubV2Agent(),
        split="development",
        knowledge_ids={item["knowledge_id"] for item in items},
        knowledge_version="test-version",
        acceptance_hash=metadata["manifest"]["acceptance_cases_sha256"],
        embedding_model="test-embedding",
        index_version="test-index",
        mode="full",
    )

    assert result["engine"] == "v2-candidate"
    assert result["metrics"]["v2_contract_illegal_outputs"] == 0
    assert result["index_version"] == "test-index"
