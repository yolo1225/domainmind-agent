import pytest
from pydantic import ValidationError

from app.agents.generation_agent import (
    ContentGenerationAgent,
    _normalize_generated_resource_payload,
)
from app.agents.legacy_contracts import GeneratedResourceDraft
from app.agents.orchestrator import OrchestratorAgent
from app.agents.retrieval_agent import KnowledgeRetrievalAgent
from app.agents.review_agent import ReviewValidationAgent
from app.services.llm_service import ModelResponseError


def test_retrieval_agent_execute_builds_retrieved_chunks(monkeypatch):
    class FakeVectorStore:
        def query(self, **kwargs):
            return {
                "ids": [["chunk_1"]],
                "documents": [["RAG chunk content"]],
                "metadatas": [
                    [
                        {
                            "knowledge_id": "k_rag",
                            "name": "RAG 检索",
                            "category": "实操技能",
                            "difficulty": 2,
                            "source_title": "测试知识库",
                            "source_url": "",
                        }
                    ]
                ],
                "distances": [[0.2]],
            }

    monkeypatch.setattr("app.agents.retrieval_agent.VectorStore", FakeVectorStore)
    monkeypatch.setattr("app.agents.retrieval_agent.embed_texts", lambda texts: [[0.1, 0.2]])

    output = KnowledgeRetrievalAgent().execute(
        {
            "domain_code": "ai_app_dev",
            "learning_goal": "学习 RAG",
            "retrieval_plan": {
                "strategy": "remedial",
                "target_difficulty": 2,
                "priority_knowledge_ids": ["k_rag"],
                "prerequisite_knowledge_ids": [],
                "query_terms": ["RAG 检索"],
                "n_results": 3,
            },
            "revision_plan": {},
        }
    )

    assert output["retrieved_chunks"][0]["knowledge_id"] == "k_rag"
    assert output["retrieved_chunks"][0]["matched_plan"] == "priority"
    assert output["trace"]["matched_priority_count"] == 1


def test_generation_agent_execute_outputs_three_sourced_resources():
    output = ContentGenerationAgent().execute(
        {
            "profile_id": "profile_1",
            "profile": {"profile_type": "beginner", "weak_knowledge": []},
            "retrieval_plan": {"strategy": "consolidation", "target_difficulty": 3},
            "revision_plan": {},
            "resource_types": ["lecture", "practice_guide", "graded_quiz"],
            "retrieved_chunks": [
                {
                    "knowledge_id": "k_prompt",
                    "name": "Prompt 工程",
                    "content": "Prompt 工程内容",
                    "source_title": "测试知识库",
                    "matched_plan": "semantic",
                    "used_for": "consolidation_practice",
                }
            ],
        }
    )

    assert len(output["draft_resources"]) == 3
    assert {item["resource_type"] for item in output["draft_resources"]} == {
        "lecture",
        "practice_guide",
        "graded_quiz",
    }
    assert all(item["sources"] for item in output["draft_resources"])


def test_generation_source_normalization_enforces_retrieval_allowlist():
    fixture = {
        "title": "RAG",
        "content": "content",
        "difficulty": 3,
        "sources": [{"knowledge_id": "k_rag", "name": "RAG"}],
    }
    normalized = _normalize_generated_resource_payload(
        {**fixture, "sources": "k_rag"}, fixture
    )
    assert normalized["sources"] == fixture["sources"]

    with pytest.raises(ModelResponseError):
        _normalize_generated_resource_payload(
            {**fixture, "sources": ["hallucinated_source"]}, fixture
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "", "content": "content", "difficulty": 3, "sources": ["k_rag"]},
        {"title": "RAG", "content": "", "difficulty": 3, "sources": ["k_rag"]},
        {"title": "RAG", "content": "content", "difficulty": 9, "sources": ["k_rag"]},
    ],
)
def test_generation_contract_rejects_missing_or_invalid_fields(payload):
    fixture = {
        "title": "RAG",
        "content": "content",
        "difficulty": 3,
        "sources": [{"knowledge_id": "k_rag", "name": "RAG"}],
    }
    normalized = _normalize_generated_resource_payload(payload, fixture)
    with pytest.raises(ValidationError):
        GeneratedResourceDraft.model_validate(normalized)


def test_review_agent_execute_marks_missing_source_as_revision_required():
    output = ReviewValidationAgent().execute(
        {
            "generation_context": {
                "sources": [],
                "generation_requirements": {
                    "difficulty": 3,
                    "strategy": "consolidation",
                },
            },
            "draft_resources": [
                {
                    "resource_type": "lecture",
                    "difficulty": 3,
                    "content": "没有来源的讲义",
                    "sources": [],
                }
            ],
        }
    )

    report = output["review_reports"][0]
    assert report["failure_level"] == "failed"
    assert output["trace"]["failed_count"] == 1


def test_review_agent_normalizes_scalar_source_ids(monkeypatch):
    model_review = {
        "factual_score": 95,
        "source_trace_score": 95,
        "difficulty_match_score": 95,
        "coverage_score": 95,
        "passed": True,
        "issues": [],
        "evidence_refs": ["k_rag"],
        "fact_checks": [
            {
                "claim": "source claim",
                "supported": True,
                "source_ids": "k_rag",
                "reason": "verified",
                "determinable": True,
            }
        ],
        "unsupported_claims": [],
        "verified_claim_count": 1,
        "source_coverage": 95,
        "unable_to_determine": [],
    }

    monkeypatch.setattr(
        "app.agents.review_agent.gateway.complete_json",
        lambda **_: (dict(model_review), {"provider_mode": "live"}),
    )
    output = ReviewValidationAgent().execute(
        {
            "generation_context": {
                "sources": [{"knowledge_id": "k_rag", "name": "RAG", "content": "RAG"}],
                "generation_requirements": {"difficulty": 3, "strategy": "consolidation"},
            },
            "draft_resources": [
                {"resource_type": "lecture", "difficulty": 3, "content": "RAG", "sources": []}
            ],
        }
    )

    assert output["review_reports"][0]["passed"] is True
    assert output["review_reports"][0]["primary_review"]["fact_checks"][0]["source_ids"] == ["k_rag"]


def test_orchestrator_agent_decide_passed_revision_and_failed():
    agent = OrchestratorAgent()

    passed = agent.decide({"review_reports": [{"passed": True}], "revision_count": 0})
    assert passed["decision"] == "passed"

    revision = agent.decide(
        {
            "review_reports": [
                {
                    "resource_type": "lecture",
                    "passed": False,
                    "revision_required": True,
                    "failure_level": "revision",
                    "source_traceability": 75,
                    "difficulty_match": 95,
                    "core_knowledge_coverage": 90,
                    "factual_accuracy": 90,
                }
            ],
            "generation_context": {
                "generation_requirements": {"strategy": "consolidation"},
            },
            "draft_resources": [{"resource_type": "lecture"}],
            "revision_count": 0,
        }
    )
    assert revision["decision"] == "revision_required"
    assert revision["revision_count"] == 1

    failed = agent.decide(
        {
            "review_reports": [{"passed": False, "failure_level": "failed"}],
            "revision_count": 0,
        }
    )
    assert failed["decision"] == "failed"
