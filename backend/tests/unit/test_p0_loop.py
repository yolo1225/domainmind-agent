from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents import nodes
from app.agents.legacy_contracts import GeneratedResourceDraft, ModelReview
from app.agents.graphs import build_learning_graph
from app.agents.checkpointer import MySQLLangGraphCheckpointer
from app.agents.base import PromptBudget
from app.agents.review_agent import ReviewValidationAgent
from app.models import (
    Base,
    GenerationTask,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningResource,
)
from app.models import GraphCheckpoint
from app.services.generation_service import persist_generated_resources
from app.services.llm_service import ModelResponseError, OpenAICompatibleGateway
from app.services.resource_export_service import _export_content
from app.workers.generation_worker import _create_profile_version_if_required


def test_unified_graph_has_exact_eight_top_level_nodes() -> None:
    graph = build_learning_graph().get_graph()
    actual = set(graph.nodes) - {"__start__", "__end__"}
    assert actual == {
        "prepare_task",
        "interpret_feedback",
        "analyze_profile",
        "retrieve_knowledge",
        "generate_resource",
        "review_resource",
        "human_review",
        "finalize_task",
    }


def test_prompt_budget_is_enforced() -> None:
    try:
        PromptBudget(2, 10).validate("content longer than the configured budget")
    except ValueError as exc:
        assert "prompt budget exceeded" in str(exc)
    else:
        raise AssertionError("prompt over budget must fail")


def test_model_gateway_retries_with_1_3_5_second_schedule(monkeypatch) -> None:
    class FailingCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            raise RuntimeError("provider unavailable")

    completions = FailingCompletions()
    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": completions})()},
    )()
    gateway = OpenAICompatibleGateway()
    monkeypatch.setattr(gateway, "_client", lambda: client)
    monkeypatch.setattr("app.services.llm_service.settings.openai_api_key", "test-key")
    sleeps: list[int] = []
    monkeypatch.setattr("app.services.llm_service.time.sleep", sleeps.append)
    try:
        gateway.complete_json(model="test-model", system_prompt="test", payload={})
    except RuntimeError as exc:
        assert "3 retries" in str(exc)
    else:
        raise AssertionError("gateway should fail after retry exhaustion")
    assert completions.calls == 4
    assert sleeps == [1, 3, 5]


def test_model_gateway_classifies_invalid_structured_output(monkeypatch) -> None:
    captured_request = {}

    def create_completion(**kwargs):
        captured_request.update(kwargs)
        return response

    response = type(
        "Response",
        (),
        {
            "choices": [
                type("Choice", (), {"message": type("Message", (), {"content": "{}"})()})()
            ],
            "usage": None,
        },
    )()
    completions = type(
        "Completions",
        (),
        {"create": lambda self, **kwargs: create_completion(**kwargs)},
    )()
    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": completions})()},
    )()
    gateway = OpenAICompatibleGateway()
    monkeypatch.setattr(gateway, "_client", lambda: client)
    monkeypatch.setattr("app.services.llm_service.settings.openai_api_key", "test-key")
    monkeypatch.setattr("app.services.llm_service.time.sleep", lambda delay: None)

    try:
        gateway.complete_json(
            model="test-model",
            system_prompt="test",
            payload={},
            response_model=GeneratedResourceDraft,
        )
    except ModelResponseError as exc:
        assert "invalid structured output" in str(exc)
    else:
        raise AssertionError("invalid model JSON must retain ModelResponseError classification")
    assert "json" in captured_request["messages"][0]["content"].lower()


def test_native_langgraph_interrupt_resumes_from_mysql_checkpoint_table() -> None:
    class ReviewState(TypedDict, total=False):
        task_id: str
        decision: str

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    checkpointer = MySQLLangGraphCheckpointer(Session)
    builder = StateGraph(ReviewState)

    def review_node(state: ReviewState) -> ReviewState:
        return {"decision": interrupt({"task_id": state["task_id"]})}

    builder.add_node("human_review", review_node)
    builder.add_edge(START, "human_review")
    builder.add_edge("human_review", END)
    graph = builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "task_native"}}
    interrupted = graph.invoke({"task_id": "task_native"}, config=config)
    assert "decision" not in interrupted
    with Session() as db:
        row = db.scalar(
            select(GraphCheckpoint).where(GraphCheckpoint.task_id == "task_native")
        )
        assert row is not None
        assert row.state_json["native_checkpoint"] is True
    resumed = graph.invoke(Command(resume="approve"), config=config)
    assert resumed["decision"] == "approve"


def test_single_subjective_feedback_does_not_update_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        nodes.ProfileAnalysisAgent,
        "execute",
        lambda self, state: {
            "profile_id": "profile_1",
            "profile_type": "beginner",
            "ability_profile": {"theory": 50},
            "weak_knowledge": [],
        },
    )
    state = nodes.analyze_profile(
        {
            "trigger_type": "resource_feedback",
            "recommended_action": "no_change",
            "learning_goal": "RAG",
            "profile_change_evidence": [
                {"type": "quick_feedback", "value": "too_hard", "confidence": 0.3}
            ],
            "agent_trace": [],
        }
    )
    assert state["profile_update_required"] is False
    assert state["needs_generation"] is False
    assert state["affected_knowledge_ids"] == []


def test_scored_evidence_updates_only_affected_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        nodes.ProfileAnalysisAgent,
        "execute",
        lambda self, state: {
            "profile_id": "profile_1",
            "profile_type": "intermediate",
            "ability_profile": {"theory": 70},
            "weak_knowledge": [],
        },
    )
    state = nodes.analyze_profile(
        {
            "trigger_type": "resource_feedback",
            "feedback_intent": "too_hard",
            "recommended_action": "update_profile",
            "learning_goal": "RAG",
            "profile_change_evidence": [
                {
                    "type": "scored_quiz",
                    "knowledge_id": "AIAPP-K029",
                    "confidence": 0.9,
                }
            ],
            "agent_trace": [],
        }
    )
    assert state["profile_update_required"] is True
    assert state["affected_knowledge_ids"] == ["AIAPP-K029"]
    assert state["affected_path_node_ids"] == ["path:AIAPP-K029"]


def test_incorrect_feedback_never_updates_profile_even_with_scored_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        nodes.ProfileAnalysisAgent,
        "execute",
        lambda self, state: {
            "profile_id": "profile_1",
            "profile_type": "intermediate",
            "ability_profile": {"theory": 70},
            "weak_knowledge": [],
        },
    )
    state = nodes.analyze_profile(
        {
            "trigger_type": "resource_feedback",
            "feedback_intent": "incorrect",
            "recommended_action": "review",
            "learning_goal": "RAG",
            "profile_change_evidence": [
                {
                    "type": "scored_quiz",
                    "knowledge_id": "AIAPP-K029",
                    "confidence": 0.9,
                }
            ],
            "agent_trace": [],
        }
    )
    assert state["profile_update_required"] is False
    assert state["needs_generation"] is True
    assert state["affected_knowledge_ids"] == []


def test_profile_update_creates_path_for_new_profile_version() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner = Learner(public_id="learner_path", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile_path_v1",
            learner_id=learner.id,
            ability_profile_json={
                "profile_type": "beginner",
                "theory": 50,
                "practice": 45,
                "problem_solving": 45,
                "breadth": 40,
                "learning_speed": 50,
            },
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        old_path = LearningPath(
            public_id="path_v1",
            learner_id=learner.id,
            profile_id=profile.id,
            domain_code="ai_app_dev",
            path_json={"stages": []},
        )
        task = GenerationTask(
            public_id="task_path_update",
            learner_id=learner.id,
            profile_id=profile.id,
            status="running",
            resource_types_json=["lecture"],
        )
        db.add_all([old_path, task])
        db.flush()
        state = {
            "profile_update_required": True,
            "profile_change_evidence": [
                {"type": "validated_behavior", "confidence": 0.8}
            ],
            "profile_update_payload": {
                "ability_profile": {
                    "profile_type": "intermediate",
                    "theory": 65,
                    "practice": 62,
                    "problem_solving": 60,
                    "breadth": 58,
                    "learning_speed": 64,
                },
                "weak_knowledge": [
                    {
                        "knowledge_id": "AIAPP-K029",
                        "name": "RAG",
                        "weakness_level": 2,
                        "prerequisites": [],
                    }
                ],
                "changed_dimensions": ["ability_scores", "weak_knowledge"],
            },
            "profile_result": {},
            "profile": {},
        }
        next_profile = _create_profile_version_if_required(
            db, task=task, profile=profile, state=state
        )
        next_path = db.scalar(
            select(LearningPath).where(LearningPath.profile_id == next_profile.id)
        )
        assert next_profile.profile_version == 2
        assert next_path is not None
        assert next_path.needs_refresh is False
        assert next_path.path_json["profile_type"] == "intermediate"
        assert old_path.needs_refresh is True
        assert state["profile_result"]["learning_path_id"] == next_path.public_id


def test_review_channels_are_two_independent_calls(monkeypatch) -> None:
    agent = ReviewValidationAgent()
    calls: list[str] = []

    def fake_call_channel(**kwargs):
        role = kwargs["role"]
        calls.append(role)
        review = ModelReview(
            model_role=role,
            factual_score=95,
            source_trace_score=95,
            difficulty_match_score=95,
            coverage_score=95,
            passed=True,
            evidence_refs=["AIAPP-K029"],
            provider_mode="fake",
        )
        return review, {"model_role": role, "model_name": f"fake-{role}"}

    monkeypatch.setattr(agent, "_call_channel", fake_call_channel)
    output = agent.execute(
        {
            "generation_context": {
                "sources": [{"knowledge_id": "AIAPP-K029", "name": "RAG"}],
                "generation_requirements": {"difficulty": 2, "strategy": "remedial"},
            },
            "draft_resources": [
                {
                    "resource_type": "lecture",
                    "difficulty": 2,
                    "content": "前置知识 RAG",
                    "sources": [{"knowledge_id": "AIAPP-K029", "name": "RAG"}],
                }
            ],
        }
    )
    assert sorted(calls) == ["primary_review_model", "secondary_review_model"]
    assert output["review_reports"][0]["passed"] is True


def test_resource_revision_creates_new_row_and_keeps_history() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        learner = Learner(public_id="learner", background="", target_domain="ai_app_dev")
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="profile",
            learner_id=learner.id,
            ability_profile_json={"profile_type": "beginner"},
            weak_knowledge_json=[],
        )
        db.add(profile)
        db.flush()
        first_task = GenerationTask(
            public_id="task_1",
            learner_id=learner.id,
            profile_id=profile.id,
            resource_types_json=["lecture"],
        )
        db.add(first_task)
        db.flush()
        state = {
            "draft_resources": [
                {
                    "resource_type": "lecture",
                    "title": "第一版",
                    "content": "正文",
                    "difficulty": 2,
                    "sources": [{"knowledge_id": "AIAPP-K029"}],
                }
            ],
            "review_reports": [{"resource_type": "lecture", "passed": True}],
        }
        persist_generated_resources(db, first_task, profile, state)
        first = db.scalar(select(LearningResource))
        second_task = GenerationTask(
            public_id="task_2",
            learner_id=learner.id,
            profile_id=profile.id,
            resource_types_json=["lecture"],
            source_resource_id=first.id,
        )
        db.add(second_task)
        db.flush()
        state["draft_resources"][0]["title"] = "第二版"
        persist_generated_resources(db, second_task, profile, state)
        resources = list(db.scalars(select(LearningResource).order_by(LearningResource.version)))
        assert [item.version for item in resources] == [1, 2]
        assert resources[0].is_current is False
        assert resources[1].is_current is True
        assert resources[1].previous_resource_id == resources[0].id
        assert resources[0].content_md == "正文"


def test_graded_quiz_export_has_learner_and_teacher_editions() -> None:
    resource = LearningResource(
        public_id="quiz_v1",
        generation_task_id=1,
        resource_type="graded_quiz",
        title="分级测验",
        content_md="题目：RAG 的作用是什么？\n参考答案：基于来源增强生成。\n解析：需保留证据链。",
        difficulty=2,
        sources_json=[],
    )
    learner_content = _export_content(resource, "learner")
    teacher_content = _export_content(resource, "teacher")
    assert "参考答案" not in learner_content
    assert "解析" not in learner_content
    assert "参考答案" in teacher_content
    assert "解析" in teacher_content
