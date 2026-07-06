from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, DiagnosticQuestion, KnowledgeItem, KnowledgeRelation, Learner
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
        background="计算机专业学生",
        target_domain="ai_app_dev",
        experience_years=0,
        learning_style="mixed",
    )
    db.add(learner)
    db.flush()

    prerequisite = KnowledgeItem(
        public_id="embedding_basic",
        domain_code="ai_app_dev",
        name="Embedding 基础",
        category="理论基础",
        difficulty=2,
        tags_json=["embedding"],
        content_md="Embedding 用向量表示语义。",
        source_title="自建知识库",
        license_note="team-authored",
        needs_reembedding=False,
    )
    rag = KnowledgeItem(
        public_id="rag_chunking",
        domain_code="ai_app_dev",
        name="RAG 切片策略",
        category="RAG 实操",
        difficulty=3,
        tags_json=["rag"],
        content_md="切片需要平衡语义完整性和召回粒度。",
        source_title="自建知识库",
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
        stem="RAG 切片的核心目标是什么？",
        options_json=["随机切分", "保持语义完整", "删除上下文"],
        answer_key_json={"correct_option": 1},
        difficulty=3,
    )
    short = DiagnosticQuestion(
        public_id="q_short",
        domain_code="ai_app_dev",
        knowledge_item_id=prerequisite.id,
        question_type="short_answer",
        stem="说明 Embedding 的作用。",
        options_json=[],
        answer_key_json={"rubric": ["向量", "语义"]},
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
                "q_short": "不知道",
            },
        )

    assert result["profile_type"] == "beginner"
    assert result["score"] == 0
    rag_weakness = next(
        item for item in result["weak_knowledge"] if item["knowledge_id"] == "rag_chunking"
    )
    assert rag_weakness["weakness_level"] >= 4
    assert "embedding_basic" in rag_weakness["prerequisites"]
    assert result["ability_profile"]["category_mastery"]["RAG 实操"] == 0
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
                "q_short": "Embedding 使用向量表示语义。",
            },
        )

    assert result["profile_type"] == "advanced"
    assert result["score"] == 100
    assert result["weak_knowledge"] == []
    assert result["ability_profile"]["category_mastery"]["理论基础"] == 100
    assert result["learning_path"]["stages"][-1]["trigger"] == "resource_feedback"
