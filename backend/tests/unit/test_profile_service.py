from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.nodes import load_profile
from app.agents.profile_agent import ProfileAnalysisAgent
from app.models import (
    AgentMessageRecord,
    AgentRun,
    Base,
    DiagnosticQuestion,
    KnowledgeItem,
    KnowledgeRelation,
    Learner,
)
from app.services.diagnostic_service import submit_diagnostic_session
from app.services.profile_service import classify_profile_level, generate_profile_from_diagnostic


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
    assert state["agent_trace"][-1]["agent_name"] == "profile_analysis_agent"
    assert state["agent_trace"][-1]["output"]["profile_source"] == "diagnostic_analysis"


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
