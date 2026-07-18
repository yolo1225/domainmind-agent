from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.agents.nodes as agent_nodes
from app.api.v1.generation_tasks import _serialize_agent_status_event
from app.agents.nodes import load_profile
from app.agents.profile_agent import ProfileAnalysisAgent
from app.models import (
    AgentMessageRecord,
    AgentRun,
    Base,
    DiagnosticQuestion,
    GenerationTask,
    KnowledgeItem,
    KnowledgeRelation,
    Learner,
    LearnerProfile,
    LearningResource,
)
from app.services.diagnostic_service import submit_diagnostic_session
from app.services.profile_service import (
    apply_feedback_profile_update,
    classify_profile_level,
    generate_profile_from_diagnostic,
)


def build_test_session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def seed_profile_fixture(db: Session) -> tuple[Learner, DiagnosticQuestion, DiagnosticQuestion]:
    learner = Learner(
        public_id="learner_001",
        background="computer science student",
        target_domain="ai_app_dev",
        experience_years=0,
        learning_style="mixed",
    )
    db.add(learner)
    db.flush()

    prerequisite = KnowledgeItem(
        public_id="embedding_basic",
        domain_code="ai_app_dev",
        name="Embedding Basics",
        category="theory_foundation",
        difficulty=2,
        tags_json=["embedding"],
        content_md="Embedding represents semantic meaning with vectors.",
        source_title="team knowledge base",
        license_note="team-authored",
        needs_reembedding=False,
    )
    rag = KnowledgeItem(
        public_id="rag_chunking",
        domain_code="ai_app_dev",
        name="RAG Chunking Strategy",
        category="rag_practice",
        difficulty=3,
        tags_json=["rag"],
        content_md="Chunking balances semantic completeness and retrieval granularity.",
        source_title="team knowledge base",
        license_note="team-authored",
        needs_reembedding=False,
    )
    db.add_all([prerequisite, rag])
    db.flush()
    db.add(
        KnowledgeRelation(
            source_item_id=rag.id,
            target_item_id=prerequisite.id,
            relation_type="prerequisite",
        )
    )

    choice = DiagnosticQuestion(
        public_id="q_choice",
        domain_code="ai_app_dev",
        knowledge_item_id=rag.id,
        question_type="single_choice",
        stem="What is the core goal of RAG chunking?",
        options_json=["random split", "semantic completeness", "delete context"],
        answer_key_json={"correct_option": 1},
        difficulty=3,
    )
    short = DiagnosticQuestion(
        public_id="q_short",
        domain_code="ai_app_dev",
        knowledge_item_id=prerequisite.id,
        question_type="short_answer",
        stem="Explain the purpose of Embedding.",
        options_json=[],
        answer_key_json={"rubric": ["vector", "semantic"]},
        difficulty=2,
    )
    db.add_all([choice, short])
    db.flush()
    return learner, choice, short


def test_classify_profile_level_boundaries() -> None:
    assert classify_profile_level(59) == "beginner"
    assert classify_profile_level(60) == "intermediate"
    assert classify_profile_level(84) == "intermediate"
    assert classify_profile_level(85) == "advanced"


def test_generate_beginner_profile_with_weak_knowledge_and_path() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_profile_fixture(db)
        result = generate_profile_from_diagnostic(
            db,
            learner=learner,
            domain_code="ai_app_dev",
            session_id="diag_low",
            questions=[choice, short],
            answer_by_question_id={
                "q_choice": 0,
                "q_short": "unknown",
            },
        )

    assert result["profile_type"] == "beginner"
    assert result["score"] == 0
    rag_weakness = next(
        item for item in result["weak_knowledge"] if item["knowledge_id"] == "rag_chunking"
    )
    assert rag_weakness["weakness_level"] >= 4
    assert "embedding_basic" in rag_weakness["prerequisites"]
    assert result["ability_profile"]["category_mastery"]["rag_practice"] == 0
    assert any(
        stage.get("resource_types") == ["lecture", "practice_guide", "graded_quiz"]
        for stage in result["learning_path"]["stages"]
    )


def test_generate_advanced_profile_without_low_score_weak_items() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_profile_fixture(db)
        result = generate_profile_from_diagnostic(
            db,
            learner=learner,
            domain_code="ai_app_dev",
            session_id="diag_high",
            questions=[choice, short],
            answer_by_question_id={
                "q_choice": 1,
                "q_short": "Embedding uses vector representation for semantic meaning.",
            },
        )

    assert result["profile_type"] == "advanced"
    assert result["score"] == 100
    assert result["weak_knowledge"] == []
    assert result["ability_profile"]["category_mastery"]["theory_foundation"] == 100
    assert result["learning_path"]["stages"][-1]["trigger"] == "resource_feedback"


def test_feedback_scope_includes_only_connected_knowledge_relations() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, _, _ = seed_profile_fixture(db)
        unrelated = KnowledgeItem(
            public_id="unrelated_item",
            domain_code="ai_app_dev",
            name="Unrelated",
            category="other",
            difficulty=2,
            tags_json=[],
            content_md="unrelated",
            source_title="team knowledge base",
            license_note="team-authored",
            needs_reembedding=False,
        )
        db.add(unrelated)
        db.flush()
        db.add(
            KnowledgeRelation(
                source_item_id=unrelated.id,
                target_item_id=unrelated.id,
                relation_type="related",
            )
        )
        profile = LearnerProfile(
            public_id="profile_feedback",
            learner_id=learner.id,
            ability_profile_json={
                "profile_type": "intermediate",
                "theory": 65,
                "practice": 60,
                "problem_solving": 60,
                "breadth": 55,
                "learning_speed": 62,
                "category_mastery": {"rag_practice": 60},
            },
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        task = GenerationTask(
            public_id="task_feedback_scope",
            learner_id=learner.id,
            profile_id=profile.id,
            status="completed",
            resource_types_json=["lecture"],
        )
        db.add(task)
        db.flush()
        resource = LearningResource(
            public_id="resource_feedback_scope",
            generation_task_id=task.id,
            resource_type="lecture",
            title="RAG",
            content_md="RAG",
            difficulty=3,
            sources_json=[{"knowledge_id": "rag_chunking"}],
            review_status="passed",
            series_id="resource_feedback_scope",
            is_current=True,
        )
        db.add(resource)
        db.flush()

        update = apply_feedback_profile_update(
            db,
            profile=profile,
            resource=resource,
            feedback_intent="too_hard",
            evidence=[{"type": "validated_behavior", "confidence": 0.8}],
        )

    assert set(update["affected_knowledge_ids"]) == {
        "rag_chunking",
        "embedding_basic",
    }
    assert "unrelated_item" not in update["affected_knowledge_ids"]
    assert update["affected_resource_ids"] == ["resource_feedback_scope"]


def test_load_profile_node_analyzes_diagnostic_answers() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_profile_fixture(db)
        state = load_profile(
            {
                "db_session": db,
                "session_id": "diag_node",
                "learner_id": learner.public_id,
                "domain_code": "ai_app_dev",
                "profile_mode": "analyze_diagnostic",
                "learning_goal": "根据诊断结果生成个性化学习资源",
                "answers": [
                    {"question_id": choice.public_id, "answer": 0},
                    {"question_id": short.public_id, "answer": "unknown"},
                ],
                "question_ids": [choice.public_id, short.public_id],
                "agent_trace": [],
            }
        )

    assert state["profile_result"]["profile_source"] == "diagnostic_analysis"
    assert state["profile_result"]["profile_type"] == "beginner"
    assert state["profile"]["weak_knowledge"]
    assert state["retrieval_plan"]["strategy"] == "remedial"
    assert state["retrieval_plan"]["target_difficulty"] == 2
    assert "rag_chunking" in state["retrieval_plan"]["priority_knowledge_ids"]
    assert "embedding_basic" in state["retrieval_plan"]["prerequisite_knowledge_ids"]
    assert "根据诊断结果生成个性化学习资源" in state["retrieval_plan"]["query_terms"]
    assert "RAG Chunking Strategy" in state["retrieval_plan"]["query_terms"]
    assert "rag_practice" in state["retrieval_plan"]["query_terms"]
    assert state["agent_trace"][-1]["agent_name"] == "profile_analysis_agent"
    assert state["agent_trace"][-1]["output"]["profile_source"] == "diagnostic_analysis"
    assert state["agent_trace"][-1]["output"]["strategy"] == "remedial"
    assert state["agent_trace"][-1]["output"]["priority_knowledge_count"] >= 1


def test_profile_analysis_agent_executes_diagnostic_mode() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_profile_fixture(db)
        result = ProfileAnalysisAgent().execute(
            {
                "db_session": db,
                "session_id": "diag_agent_class",
                "learner_id": learner.public_id,
                "domain_code": "ai_app_dev",
                "profile_mode": "analyze_diagnostic",
                "answers": [
                    {"question_id": choice.public_id, "answer": 1},
                    {
                        "question_id": short.public_id,
                        "answer": "Embedding uses vector representation for semantic meaning.",
                    },
                ],
                "question_ids": [choice.public_id, short.public_id],
            }
        )

    assert result["profile_source"] == "diagnostic_analysis"
    assert result["profile_type"] == "advanced"
    assert result["learning_path_id"].startswith("path_")


def test_load_profile_node_loads_existing_profile() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_profile_fixture(db)
        generated = generate_profile_from_diagnostic(
            db,
            learner=learner,
            domain_code="ai_app_dev",
            session_id="diag_existing",
            questions=[choice, short],
            answer_by_question_id={
                "q_choice": 1,
                "q_short": "Embedding uses vector representation for semantic meaning.",
            },
        )
        state = load_profile(
            {
                "db_session": db,
                "learner_id": learner.public_id,
                "profile_id": generated["profile_id"],
                "domain_code": "ai_app_dev",
                "profile_mode": "load_existing_profile",
                "agent_trace": [],
            }
        )

    assert state["profile_result"]["profile_source"] == "existing_profile"
    assert state["profile_id"] == generated["profile_id"]
    assert state["profile"]["profile_type"] == "advanced"
    assert state["profile_result"]["learning_path_id"] == generated["learning_path_id"]
    assert state["retrieval_plan"]["strategy"] == "challenge"
    assert state["retrieval_plan"]["target_difficulty"] == 4
    assert state["retrieval_plan"]["priority_knowledge_ids"] == []


def test_retrieve_knowledge_uses_retrieval_plan_query_and_result_count(monkeypatch) -> None:
    captured: dict = {}

    def fake_embed_texts(texts):
        captured["texts"] = texts
        return [[0.1, 0.2, 0.3]]

    class FakeVectorStore:
        def query(self, *, domain_code, query_embeddings, n_results, where=None):
            captured["domain_code"] = domain_code
            captured["query_embeddings"] = query_embeddings
            captured["n_results"] = n_results
            return {
                "ids": [["chunk_001", "chunk_002", "chunk_003"]],
                "documents": [
                    [
                        "Chunking balances semantic completeness and retrieval granularity.",
                        "Embedding represents semantic meaning with vectors.",
                        "Agent review checks source traceability.",
                    ]
                ],
                "metadatas": [
                    [
                        {
                            "knowledge_id": "rag_chunking",
                            "name": "RAG Chunking Strategy",
                            "category": "rag_practice",
                            "difficulty": 3,
                            "source_title": "team knowledge base",
                            "source_url": "",
                        },
                        {
                            "knowledge_id": "embedding_basic",
                            "name": "Embedding Basics",
                            "category": "theory_foundation",
                            "difficulty": 2,
                            "source_title": "team knowledge base",
                            "source_url": "",
                        },
                        {
                            "knowledge_id": "agent_review",
                            "name": "Agent Review",
                            "category": "agent_practice",
                            "difficulty": 3,
                            "source_title": "team knowledge base",
                            "source_url": "",
                        }
                    ]
                ],
                "distances": [[0.25, 0.5, 0.75]],
            }

    monkeypatch.setattr(agent_nodes, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(agent_nodes, "VectorStore", FakeVectorStore)

    state = agent_nodes.retrieve_knowledge(
        {
            "domain_code": "ai_app_dev",
            "retrieval_plan": {
                "strategy": "remedial",
                "target_difficulty": 2,
                "priority_knowledge_ids": ["rag_chunking"],
                "prerequisite_knowledge_ids": ["embedding_basic"],
                "query_terms": ["补救讲解", "RAG Chunking Strategy", "rag_practice"],
                "n_results": 7,
            },
            "agent_trace": [],
        }
    )

    assert captured["texts"] == ["补救讲解 RAG Chunking Strategy rag_practice"]
    assert captured["domain_code"] == "ai_app_dev"
    assert captured["n_results"] == 7
    assert state["retrieved_chunks"][0]["knowledge_id"] == "rag_chunking"
    assert state["retrieved_chunks"][0]["selection_reason"] == "retrieval_plan:remedial"
    assert state["retrieved_chunks"][0]["matched_plan"] == "priority"
    assert state["retrieved_chunks"][1]["matched_plan"] == "prerequisite"
    assert state["retrieved_chunks"][2]["matched_plan"] == "semantic"
    assert state["retrieved_chunks"][0]["used_for"] == "remedial_explanation"
    assert state["retrieved_chunks"][0]["target_difficulty"] == 2
    assert state["agent_trace"][-1]["output"]["strategy"] == "remedial"
    assert state["agent_trace"][-1]["output"]["priority_knowledge_ids"] == ["rag_chunking"]
    assert state["agent_trace"][-1]["output"]["matched_priority_count"] == 1
    assert state["agent_trace"][-1]["output"]["matched_prerequisite_count"] == 1
    assert state["agent_trace"][-1]["output"]["semantic_count"] == 1


def generation_state_for_strategy(strategy: str, difficulty: int) -> dict:
    return {
        "profile_id": "profile_001",
        "profile": {
            "profile_id": "profile_001",
            "profile_type": "beginner" if strategy == "remedial" else "advanced",
            "theory": 60,
            "practice": 55,
            "weak_knowledge": [
                {
                    "knowledge_id": "rag_chunking",
                    "name": "RAG Chunking Strategy",
                    "weakness_level": 4,
                }
            ],
        },
        "retrieval_plan": {
            "strategy": strategy,
            "target_difficulty": difficulty,
            "priority_knowledge_ids": ["rag_chunking"],
            "prerequisite_knowledge_ids": ["embedding_basic"],
        },
        "retrieved_chunks": [
            {
                "chunk_id": "chunk_001",
                "knowledge_id": "rag_chunking",
                "name": "RAG Chunking Strategy",
                "category": "rag_practice",
                "difficulty": 3,
                "content": "Chunking balances semantic completeness and retrieval granularity.",
                "source_title": "team knowledge base",
                "matched_plan": "priority",
                "used_for": "remedial_explanation"
                if strategy == "remedial"
                else "challenge_task"
                if strategy == "challenge"
                else "consolidation_practice",
            }
        ],
        "resource_types": ["lecture", "practice_guide", "graded_quiz"],
        "agent_trace": [],
    }


def assert_generated_resources_follow_context(state: dict, expected_difficulty: int) -> None:
    assert state["generation_context"]["generation_requirements"]["difficulty"] == expected_difficulty
    assert state["generation_context"]["generation_requirements"]["must_include_sources"] is True
    assert state["generation_context"]["generation_requirements"]["source_policy"] == (
        "cite_retrieved_knowledge_only"
    )
    assert len(state["draft_resources"]) == 3
    for resource in state["draft_resources"]:
        assert resource["sources"]
        assert resource["difficulty"] == expected_difficulty
        assert resource["sources"][0]["matched_plan"] == "priority"


def test_generate_resource_uses_remedial_context() -> None:
    state = agent_nodes.generate_resource(generation_state_for_strategy("remedial", 2))

    assert_generated_resources_follow_context(state, 2)
    lecture = next(item for item in state["draft_resources"] if item["resource_type"] == "lecture")
    assert "前置知识" in lecture["content"]
    assert "常见误区" in lecture["content"]
    assert "补救讲解" in lecture["content"]


def test_generate_resource_uses_consolidation_context() -> None:
    state = agent_nodes.generate_resource(generation_state_for_strategy("consolidation", 3))

    assert_generated_resources_follow_context(state, 3)
    contents = "\n".join(item["content"] for item in state["draft_resources"])
    assert "检查点" in contents
    assert "巩固练习" in contents


def test_generate_resource_uses_challenge_context() -> None:
    state = agent_nodes.generate_resource(generation_state_for_strategy("challenge", 4))

    assert_generated_resources_follow_context(state, 4)
    contents = "\n".join(item["content"] for item in state["draft_resources"])
    assert "挑战任务" in contents
    assert "扩展问题" in contents


def test_review_resource_passes_valid_remedial_resources() -> None:
    state = agent_nodes.generate_resource(generation_state_for_strategy("remedial", 2))
    state = agent_nodes.review_resource(state)

    assert state["review_reports"]
    assert all(report["passed"] for report in state["review_reports"])
    assert all(report["factual_accuracy"] >= 80 for report in state["review_reports"])
    assert all(report["source_traceability"] >= 80 for report in state["review_reports"])
    assert all(report["difficulty_match"] >= 80 for report in state["review_reports"])
    assert all(report["core_knowledge_coverage"] >= 80 for report in state["review_reports"])
    assert state["agent_trace"][-1]["output"]["passed"] is True


def test_review_resource_fails_when_sources_missing() -> None:
    state = agent_nodes.generate_resource(generation_state_for_strategy("remedial", 2))
    state["draft_resources"][0]["sources"] = []
    state = agent_nodes.review_resource(state)
    report = state["review_reports"][0]

    assert report["source_traceability"] == 0
    assert report["failure_level"] == "failed"
    assert report["passed"] is False


def test_review_resource_requests_revision_for_near_difficulty_mismatch() -> None:
    state = agent_nodes.generate_resource(generation_state_for_strategy("remedial", 2))
    state["draft_resources"][0]["difficulty"] = 3
    state = agent_nodes.review_resource(state)
    report = state["review_reports"][0]

    assert report["difficulty_match"] == 75
    assert report["revision_required"] is True
    assert report["failure_level"] == "revision"
    assert report["passed"] is False


def test_review_resource_requests_revision_for_missing_challenge_coverage() -> None:
    state = agent_nodes.generate_resource(generation_state_for_strategy("challenge", 4))
    state["draft_resources"][0]["content"] = (
        "# 普通讲义\n\nRAG Chunking Strategy rag_chunking\n\n## 来源知识\n"
    )
    state = agent_nodes.review_resource(state)
    report = state["review_reports"][0]

    assert report["core_knowledge_coverage"] == 70
    assert report["revision_required"] is True
    assert report["failure_level"] == "revision"
    assert report["passed"] is False


def test_decide_next_step_passes_all_reviewed_resources() -> None:
    state = agent_nodes.decide_next_step(
        {
            "review_reports": [
                {"passed": True, "failure_level": "none"},
                {"passed": True, "failure_level": "none"},
            ],
            "revision_count": 0,
            "agent_trace": [],
        }
    )

    assert state["decision"] == "passed"


def test_decide_next_step_requests_revision_for_revision_reports() -> None:
    state = agent_nodes.decide_next_step(
        {
            "review_reports": [
                {
                    "resource_type": "lecture",
                    "passed": False,
                    "revision_required": True,
                    "failure_level": "revision",
                    "source_traceability": 60,
                    "difficulty_match": 95,
                    "core_knowledge_coverage": 90,
                    "factual_accuracy": 55,
                }
            ],
            "generation_context": {
                "generation_requirements": {"strategy": "remedial", "difficulty": 2}
            },
            "revision_count": 0,
            "agent_trace": [],
        }
    )

    assert state["decision"] == "revision_required"
    assert state["revision_count"] == 1
    assert state["revision_plan"]["revision_required"] is True
    assert state["revision_plan"]["revision_resource_types"] == ["lecture"]
    assert "source_traceability" in state["revision_plan"]["issues_by_resource_type"]["lecture"]
    assert "补充来源引用" in state["revision_plan"]["missing_requirements"]


def test_decide_next_step_fails_for_failed_review_reports() -> None:
    state = agent_nodes.decide_next_step(
        {
            "review_reports": [{"passed": False, "failure_level": "failed"}],
            "revision_count": 0,
            "agent_trace": [],
        }
    )

    assert state["decision"] == "failed"
    assert state["revision_count"] == 0


def test_decide_next_step_fails_after_revision_limit() -> None:
    state = agent_nodes.decide_next_step(
        {
            "review_reports": [
                {
                    "resource_type": "lecture",
                    "passed": False,
                    "revision_required": True,
                    "failure_level": "revision",
                    "source_traceability": 95,
                    "difficulty_match": 75,
                    "core_knowledge_coverage": 90,
                    "factual_accuracy": 90,
                }
            ],
            "revision_count": 2,
            "agent_trace": [],
        }
    )

    assert state["decision"] == "failed"
    assert state["revision_plan"] == {}


def test_route_after_decision_allows_revision_round_at_limit_boundary() -> None:
    assert (
        agent_nodes.route_after_decision(
            {"decision": "revision_required", "revision_count": 2}
        )
        == "retrieve_knowledge"
    )
    assert agent_nodes.route_after_decision({"decision": "failed", "revision_count": 2}) == "end"


def test_decide_next_step_preserves_passed_resources_for_revision() -> None:
    state = agent_nodes.generate_resource(generation_state_for_strategy("challenge", 4))
    state["draft_resources"][0]["content"] = (
        "# 普通讲义\n\nRAG Chunking Strategy rag_chunking\n\n## 来源知识\n"
    )
    state = agent_nodes.review_resource(state)
    state = agent_nodes.decide_next_step(state)

    assert state["decision"] == "revision_required"
    assert state["revision_plan"]["revision_resource_types"] == ["lecture"]
    assert len(state["passed_resources"]) == 2
    assert {resource["resource_type"] for resource in state["passed_resources"]} == {
        "practice_guide",
        "graded_quiz",
    }


def test_retrieve_knowledge_uses_revision_plan_query_and_boost(monkeypatch) -> None:
    captured: dict = {}

    def fake_embed_texts(texts):
        captured["texts"] = texts
        return [[0.1, 0.2, 0.3]]

    class FakeVectorStore:
        def query(self, *, domain_code, query_embeddings, n_results, where=None):
            captured["n_results"] = n_results
            return {
                "ids": [["chunk_001"]],
                "documents": [["Chunking balances semantic completeness."]],
                "metadatas": [
                    [
                        {
                            "knowledge_id": "rag_chunking",
                            "name": "RAG Chunking Strategy",
                            "category": "rag_practice",
                            "difficulty": 3,
                            "source_title": "team knowledge base",
                            "source_url": "",
                        }
                    ]
                ],
                "distances": [[0.25]],
            }

    monkeypatch.setattr(agent_nodes, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(agent_nodes, "VectorStore", FakeVectorStore)

    state = agent_nodes.retrieve_knowledge(
        {
            "domain_code": "ai_app_dev",
            "retrieval_plan": {
                "strategy": "remedial",
                "target_difficulty": 2,
                "priority_knowledge_ids": ["rag_chunking"],
                "prerequisite_knowledge_ids": [],
                "query_terms": ["RAG Chunking Strategy"],
                "n_results": 5,
            },
            "revision_plan": {
                "revision_required": True,
                "query_terms": ["补充来源引用"],
                "n_results_boost": 3,
            },
            "agent_trace": [],
        }
    )

    assert captured["texts"] == ["RAG Chunking Strategy 补充来源引用"]
    assert captured["n_results"] == 8
    assert state["agent_trace"][-1]["output"]["revision_required"] is True
    assert state["agent_trace"][-1]["output"]["revision_query_terms"] == ["补充来源引用"]


def test_generate_resource_revises_only_failed_resource_and_keeps_passed_resources() -> None:
    first_pass = agent_nodes.generate_resource(generation_state_for_strategy("challenge", 4))
    passed_resources = [
        resource
        for resource in first_pass["draft_resources"]
        if resource["resource_type"] != "lecture"
    ]
    state = {
        **generation_state_for_strategy("challenge", 4),
        "passed_resources": passed_resources,
        "revision_plan": {
            "revision_required": True,
            "revision_resource_types": ["lecture"],
            "missing_requirements": ["挑战任务", "扩展问题", "扩展边界"],
        },
    }
    revised = agent_nodes.generate_resource(state)

    assert len(revised["draft_resources"]) == 3
    assert [resource["resource_type"] for resource in revised["draft_resources"]].count(
        "lecture"
    ) == 1
    lecture = next(
        resource for resource in revised["draft_resources"] if resource["resource_type"] == "lecture"
    )
    assert "挑战任务" in lecture["content"]
    assert "扩展问题" in lecture["content"]
    assert "修订要求" in lecture["content"]
    assert {resource["resource_type"] for resource in revised["passed_resources"]} == {
        "practice_guide",
        "graded_quiz",
    }


def test_submit_diagnostic_session_records_profile_analysis_agent() -> None:
    testing_session = build_test_session()
    with testing_session() as db:
        learner, choice, short = seed_profile_fixture(db)
        result = submit_diagnostic_session(
            db,
            session_id="diag_agent",
            learner_id=learner.public_id,
            domain_code="ai_app_dev",
            answers=[
                {"question_id": choice.public_id, "answer": 1},
                {
                    "question_id": short.public_id,
                    "answer": "Embedding uses vector representation for semantic meaning.",
                },
            ],
        )

        run = db.query(AgentRun).filter_by(agent_name="profile_analysis_agent").one()
        messages = db.query(AgentMessageRecord).filter_by(session_id="diag_agent").all()

    assert result["agent_run_id"] == run.id
    assert result["agent_name"] == "profile_analysis_agent"
    assert run.generation_task_id is None
    assert run.status == "completed"
    assert run.input_summary_json["session_id"] == "diag_agent"
    assert run.input_summary_json["profile_mode"] == "analyze_diagnostic"
    assert run.output_summary_json["profile_id"] == result["profile_id"]
    assert run.output_summary_json["profile_type"] == result["profile_type"]
    assert len(messages) >= 2
    assert {message.message_type for message in messages} >= {"command", "result"}


def test_agent_status_event_extracts_round_and_filters_sensitive_payload() -> None:
    task = GenerationTask(
        public_id="task_sse",
        learner_id=1,
        profile_id=1,
        domain_code="ai_app_dev",
        status="running",
        resource_types_json=["lecture"],
        revision_count=1,
        decision="pending",
    )
    run = AgentRun(
        id=77,
        generation_task_id=1,
        agent_name="content_generation_agent",
        status="completed",
        input_summary_json={
            "task_id": "task_sse",
            "step": "generate_resource",
            "generation_round": 2,
        },
        output_summary_json={
            "step": "generate_resource",
            "resource_count": 3,
            "generated_resource_count": 1,
            "preserved_resource_count": 2,
            "strategy": "remedial",
            "content": "完整资源正文不应出现在 SSE 中",
            "profile": {"weak_knowledge": ["完整画像不应出现在 SSE 中"]},
        },
    )

    event = _serialize_agent_status_event(task, run, "generate_resource")

    assert event["run_id"] == 77
    assert event["generation_round"] == 2
    assert event["is_revision_round"] is True
    assert "第 2 轮" in event["event_message"]
    assert event["payload"]["resource_count"] == 3
    assert "content" not in event["payload"]
    assert "profile" not in event["payload"]
