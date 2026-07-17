from __future__ import annotations

from datetime import UTC, datetime

from app.agents.contract_adapters import render_resource_markdown
from app.agents.contracts import (
    AgentMessage,
    AgentName,
    AbilityScores,
    AffectedScope,
    AnalyzeProfileInput,
    AnalyzeProfileOutput,
    ArbitrationResult,
    ConceptBlock,
    ConversationSummary,
    DiagnosticSummary,
    EvidenceRef,
    EvidenceType,
    ExecutionMode,
    FactCheck,
    FeedbackContext,
    FeedbackIntent,
    FinalizeTaskInput,
    FinalizeTaskOutput,
    GenerateResourceInput,
    GenerateResourceOutput,
    GeneratedResourceArtifact,
    GenerationRequirements,
    GenerationStrategy,
    GradedQuizContent,
    HumanDecision,
    HumanReviewInput,
    HumanReviewOutput,
    InterpretFeedbackInput,
    InterpretFeedbackOutput,
    LectureContent,
    MasteryType,
    MisconceptionBlock,
    ModelReview,
    MessagePayload,
    MessageType,
    NodeName,
    PracticeGuideContent,
    PracticeStep,
    PrepareTaskInput,
    PrepareTaskOutput,
    ProfileSnapshot,
    ProfileType,
    QuestionType,
    QuizLevel,
    QuizQuestion,
    RecommendedAction,
    ResourceSummary,
    ResourceType,
    RetrieveKnowledgeInput,
    RetrieveKnowledgeOutput,
    RetrievalMatchType,
    RetrievalPlan,
    RetrievalPurpose,
    ReviewCriterionScores,
    ReviewDecision,
    ReviewReport,
    ReviewResourceInput,
    ReviewResourceOutput,
    RetrievedChunk,
    SourceRef,
    TaskContext,
    TaskDecision,
    TaskRequest,
    TriggerType,
    WeakKnowledge,
)


TASK_ID = "task_contract_example"
SOURCE = SourceRef(
    source_ref_id="AIAPP-K029::chunk::0",
    knowledge_id="AIAPP-K029",
    source_title="自建 AI 应用开发实训知识库",
    source_url=None,
    license_note="team-authored",
)
PROFILE = ProfileSnapshot(
    profile_id="profile_contract_example",
    profile_version=1,
    profile_type=ProfileType.BEGINNER,
    ability_scores=AbilityScores(
        theory=55,
        practice=40,
        problem_solving=48,
        knowledge_breadth=52,
        learning_speed=60,
    ),
    weak_knowledge=[
        WeakKnowledge(
            knowledge_id="AIAPP-K029",
            name="RAG 检索与来源追溯",
            category="RAG",
            weakness_level=4,
            mastery_type=MasteryType.PARTIAL_MASTERY,
            prerequisite_ids=["AIAPP-K028"],
            evidence_ids=["evidence_diag_1"],
            reason="检索和重排题目得分较低",
        )
    ],
    blind_spot_ids=[],
)
PLAN = RetrievalPlan(
    strategy=GenerationStrategy.REMEDIAL,
    target_difficulty=2,
    resource_types=[ResourceType.LECTURE],
    priority_knowledge_ids=["AIAPP-K029"],
    prerequisite_knowledge_ids=["AIAPP-K028"],
    query_terms=["RAG 检索", "来源追溯"],
    n_results=8,
)


def agent_message_example() -> AgentMessage:
    return AgentMessage(
        message_id="message_contract_example",
        sender=AgentName.ORCHESTRATOR,
        receiver=AgentName.KNOWLEDGE_RETRIEVAL,
        message_type=MessageType.COMMAND,
        payload=MessagePayload(
            node_name=NodeName.RETRIEVE_KNOWLEDGE,
            summary="按画像薄弱点检索 RAG 来源证据",
            reference_ids=["AIAPP-K029"],
        ),
        timestamp=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        session_id=TASK_ID,
        task_id=TASK_ID,
    )


def _initial_context() -> TaskContext:
    return TaskContext(
        task_id=TASK_ID,
        session_id=TASK_ID,
        trigger_type=TriggerType.INITIAL_GENERATION,
        execution_mode=ExecutionMode.AUTO,
        learner_id="learner_001",
        profile_id=PROFILE.profile_id,
        domain_code="ai_app_dev",
        resource_types=[ResourceType.LECTURE],
        learning_goal="掌握 RAG 检索与来源追溯",
    )


def _feedback_context() -> TaskContext:
    return TaskContext(
        task_id="task_feedback_example",
        session_id="task_feedback_example",
        trigger_type=TriggerType.RESOURCE_FEEDBACK,
        execution_mode=ExecutionMode.AUTO,
        learner_id="learner_001",
        profile_id=PROFILE.profile_id,
        domain_code="ai_app_dev",
        resource_types=[ResourceType.LECTURE],
        learning_goal="理解 RAG 检索",
        resource_id="resource_lecture_v1",
        feedback_id="feedback_001",
        tutoring_session_id="tutoring_001",
        tutoring_message_id="message_001",
    )


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="AIAPP-K029::chunk::0",
        knowledge_id="AIAPP-K029",
        name="RAG 检索与来源追溯",
        category="RAG",
        difficulty=2,
        content="RAG 检索需要保留知识片段与来源标识，生成内容只能引用已检索证据。",
        similarity=0.92,
        matched_by=RetrievalMatchType.PRIORITY,
        used_for=RetrievalPurpose.REMEDIAL_EXPLANATION,
        source=SOURCE,
    )


def _requirements(resource_types: list[ResourceType]) -> GenerationRequirements:
    return GenerationRequirements(
        resource_types=resource_types,
        target_difficulty=2,
        strategy=GenerationStrategy.REMEDIAL,
        required_knowledge_ids=["AIAPP-K029"],
        source_whitelist=[SOURCE.source_ref_id],
        adaptation_notes=["使用小步解释和明确检查点"],
    )


def _lecture_artifact() -> GeneratedResourceArtifact:
    content = LectureContent(
        title="RAG 检索与来源追溯讲义",
        target_audience="RAG 初学者",
        learning_objectives=["能说明检索片段与来源引用的关系"],
        prerequisite_knowledge=["文本向量基础"],
        core_concepts=[
            ConceptBlock(
                title="可追溯检索",
                explanation="检索结果必须携带稳定的来源标识。",
                example="生成讲义中的事实引用 AIAPP-K029::chunk::0。",
                source_ref_ids=[SOURCE.source_ref_id],
            )
        ],
        misconceptions=[
            MisconceptionBlock(
                misconception="只要语义相似就不需要来源。",
                correction="语义匹配负责召回，来源标识负责追溯。",
                source_ref_ids=[SOURCE.source_ref_id],
            )
        ],
        summary="可靠 RAG 需要同时保留检索内容和来源引用。",
    )
    return GeneratedResourceArtifact(
        resource_type=ResourceType.LECTURE,
        structured_content=content,
        content_md=render_resource_markdown(content, [SOURCE]),
        difficulty=2,
        source_refs=[SOURCE],
    )


def _practice_artifact() -> GeneratedResourceArtifact:
    content = PracticeGuideContent(
        title="RAG 检索证据链实操",
        target_audience="具备 Python 基础的初学者",
        learning_objectives=["完成一次带来源的向量检索"],
        environment_requirements=["Python 3.12", "ChromaDB"],
        steps=[
            PracticeStep(
                order=1,
                title="执行检索",
                instruction="使用学习目标构造查询并保留来源标识。",
                code_or_command="python -m app.scripts.build_chroma_index --json",
                expected_result="返回知识点 ID 和来源标题。",
                troubleshooting="无结果时检查索引状态。",
                source_ref_ids=[SOURCE.source_ref_id],
            )
        ],
        acceptance_criteria=["检索结果包含 knowledge_id 和 source_ref_id"],
    )
    return GeneratedResourceArtifact(
        resource_type=ResourceType.PRACTICE_GUIDE,
        structured_content=content,
        content_md=render_resource_markdown(content, [SOURCE]),
        difficulty=2,
        source_refs=[SOURCE],
    )


def _quiz_artifact() -> GeneratedResourceArtifact:
    questions: list[QuizQuestion] = []
    for index, level in enumerate(
        [
            QuizLevel.FOUNDATION,
            QuizLevel.FOUNDATION,
            QuizLevel.IMPROVEMENT,
            QuizLevel.IMPROVEMENT,
            QuizLevel.CHALLENGE,
            QuizLevel.CHALLENGE,
        ],
        start=1,
    ):
        questions.append(
            QuizQuestion(
                question_id=f"Q{index}",
                level=level,
                question_type=QuestionType.SHORT_ANSWER,
                prompt=f"说明 RAG 证据链检查点 {index}。",
                correct_answer="结果应包含知识点、片段和来源标识。",
                explanation="完整证据链用于事实复核。",
                knowledge_id="AIAPP-K029",
                difficulty=min(5, 1 + index // 2),
                source_ref_ids=[SOURCE.source_ref_id],
            )
        )
    content = GradedQuizContent(
        title="RAG 检索分级测验",
        target_audience="RAG 初学者",
        learning_objectives=["检查检索和来源追溯能力"],
        questions=questions,
    )
    return GeneratedResourceArtifact(
        resource_type=ResourceType.GRADED_QUIZ,
        structured_content=content,
        content_md=render_resource_markdown(content, [SOURCE]),
        difficulty=2,
        source_refs=[SOURCE],
    )


def resource_examples() -> list[GeneratedResourceArtifact]:
    return [_lecture_artifact(), _practice_artifact(), _quiz_artifact()]


def _passed_review(resource_type: ResourceType) -> ReviewReport:
    scores = ReviewCriterionScores(
        factual_accuracy=95,
        source_traceability=96,
        difficulty_match=92,
        core_knowledge_coverage=94,
    )
    fact_check = FactCheck(
        claim="RAG 资源需保留来源标识。",
        supported=True,
        source_ref_ids=[SOURCE.source_ref_id],
        reason="检索证据明确支持该声明。",
    )
    primary = ModelReview(
        model_role="primary_review_model",
        model_name="review-primary",
        scores=scores,
        passed=True,
        fact_checks=[fact_check],
    )
    secondary = ModelReview(
        model_role="secondary_review_model",
        model_name="review-secondary",
        scores=scores,
        passed=True,
        fact_checks=[fact_check],
    )
    return ReviewReport(
        resource_type=resource_type,
        primary_review=primary,
        secondary_review=secondary,
        final_scores=scores,
        arbitration=ArbitrationResult(
            required=False,
            retrieval_performed=False,
            disagreement_remains=False,
        ),
        evidence_ref_ids=[SOURCE.source_ref_id],
        decision=ReviewDecision.PASSED,
        passed=True,
        manual_review_required=False,
    )


def initial_generation_flow_example() -> dict[str, object]:
    context = _initial_context()
    request = TaskRequest.model_validate(context.model_dump(exclude={"contract_version"}))
    diagnostic = DiagnosticSummary(
        diagnostic_session_id="diagnostic_001",
        question_count=10,
        answered_count=10,
        correct_count=5,
        skipped_count=0,
        score_percent=50,
        evidence=[
            EvidenceRef(
                evidence_id="evidence_diag_1",
                evidence_type=EvidenceType.DIAGNOSTIC_RESULT,
                summary="RAG 检索题目得分较低",
                knowledge_id="AIAPP-K029",
                confidence=0.95,
                confirmed=True,
            )
        ],
    )
    prepare_input = PrepareTaskInput(task_id=TASK_ID, request=request)
    prepare_output = PrepareTaskOutput(
        task_id=TASK_ID, context=context, next_node="analyze_profile"
    )
    analyze_input = AnalyzeProfileInput(
        task_id=TASK_ID,
        context=context,
        current_profile=PROFILE,
        diagnostic_summary=diagnostic,
    )
    analyze_output = AnalyzeProfileOutput(
        task_id=TASK_ID,
        profile=PROFILE,
        profile_update_required=False,
        evidence_refs=diagnostic.evidence,
        confidence=0.95,
        decision_reason="初次生成使用已有诊断画像",
        affected_scope=AffectedScope(knowledge_ids=["AIAPP-K029"]),
        retrieval_plan=PLAN,
        needs_generation=True,
    )
    chunk = _chunk()
    retrieve_input = RetrieveKnowledgeInput(
        task_id=TASK_ID,
        context=context,
        profile=PROFILE,
        retrieval_plan=PLAN,
        purpose=RetrievalPurpose.REMEDIAL_EXPLANATION,
    )
    retrieve_output = RetrieveKnowledgeOutput(
        task_id=TASK_ID,
        query_text="RAG 检索 来源追溯",
        chunks=[chunk],
        covered_knowledge_ids=["AIAPP-K029"],
        missing_knowledge_ids=["AIAPP-K028"],
        warnings=["前置知识将在后续关系扩展中补充"],
    )
    requirements = _requirements([ResourceType.LECTURE])
    generate_input = GenerateResourceInput(
        task_id=TASK_ID,
        context=context,
        profile=PROFILE,
        retrieved_chunks=[chunk],
        requirements=requirements,
    )
    lecture = _lecture_artifact()
    generate_output = GenerateResourceOutput(task_id=TASK_ID, resources=[lecture])
    review_input = ReviewResourceInput(
        task_id=TASK_ID,
        context=context,
        resources=[lecture],
        requirements=requirements,
        evidence=[chunk],
    )
    report = _passed_review(ResourceType.LECTURE)
    review_output = ReviewResourceOutput(task_id=TASK_ID, reports=[report])
    finalize_input = FinalizeTaskInput(
        task_id=TASK_ID,
        context=context,
        resources=[lecture],
        review_reports=[report],
        revision_count=0,
    )
    finalize_output = FinalizeTaskOutput(
        task_id=TASK_ID,
        decision=TaskDecision.COMPLETED,
        revision_count=0,
        passed_resource_types=[ResourceType.LECTURE],
        manual_review_required=False,
        decision_reason="两路审核通过",
    )
    return {
        "prepare_task": {"input": prepare_input, "output": prepare_output},
        "analyze_profile": {"input": analyze_input, "output": analyze_output},
        "retrieve_knowledge": {"input": retrieve_input, "output": retrieve_output},
        "generate_resource": {"input": generate_input, "output": generate_output},
        "review_resource": {"input": review_input, "output": review_output},
        "finalize_task": {"input": finalize_input, "output": finalize_output},
    }


def feedback_flow_example() -> dict[str, object]:
    context = _feedback_context()
    request = TaskRequest.model_validate(context.model_dump(exclude={"contract_version"}))
    feedback = FeedbackContext(
        resource=ResourceSummary(
            resource_id="resource_lecture_v1",
            resource_type=ResourceType.LECTURE,
            title="RAG 讲义",
            difficulty=2,
            source_ref_ids=[SOURCE.source_ref_id],
        ),
        conversation=ConversationSummary(
            tutoring_session_id="tutoring_001",
            turn_count=1,
            latest_message_summary="这一节有点难",
        ),
        feedback_summary="学习者表示当前讲解偏难",
        quick_tag=FeedbackIntent.TOO_HARD,
        rating=2,
    )
    prepare_input = PrepareTaskInput(task_id=context.task_id, request=request)
    prepare_output = PrepareTaskOutput(
        task_id=context.task_id, context=context, next_node="interpret_feedback"
    )
    tutoring_input = InterpretFeedbackInput(
        task_id=context.task_id,
        context=context,
        profile=PROFILE,
        feedback=feedback,
    )
    evidence = EvidenceRef(
        evidence_id="evidence_feedback_1",
        evidence_type=EvidenceType.QUICK_FEEDBACK,
        summary="单次 too_hard 快捷反馈",
        knowledge_id="AIAPP-K029",
        confidence=0.3,
    )
    tutoring_output = InterpretFeedbackOutput(
        task_id=context.task_id,
        feedback_intent=FeedbackIntent.TOO_HARD,
        recommended_action=RecommendedAction.ASK_FOLLOW_UP,
        reply="请说明是检索过程还是来源引用不易理解。",
        evidence=[evidence],
        needs_generation=False,
        decision_reason="单次主观反馈证据不足",
    )
    analyze_input = AnalyzeProfileInput(
        task_id=context.task_id,
        context=context,
        current_profile=PROFILE,
        feedback_evidence=[evidence],
        recommended_action=RecommendedAction.ASK_FOLLOW_UP,
    )
    analyze_output = AnalyzeProfileOutput(
        task_id=context.task_id,
        profile=PROFILE,
        profile_update_required=False,
        evidence_refs=[evidence],
        confidence=0.3,
        decision_reason="证据不足，保留原画像",
        affected_scope=AffectedScope(),
        retrieval_plan=PLAN,
        needs_generation=False,
    )
    finalize_input = FinalizeTaskInput(
        task_id=context.task_id,
        context=context,
        revision_count=0,
        tutoring_result=tutoring_output,
    )
    finalize_output = FinalizeTaskOutput(
        task_id=context.task_id,
        decision=TaskDecision.NO_CHANGE,
        revision_count=0,
        manual_review_required=False,
        decision_reason="证据不足，仅继续追问",
    )
    return {
        "prepare_task": {"input": prepare_input, "output": prepare_output},
        "interpret_feedback": {"input": tutoring_input, "output": tutoring_output},
        "analyze_profile": {"input": analyze_input, "output": analyze_output},
        "finalize_task": {"input": finalize_input, "output": finalize_output},
    }


def human_review_example() -> dict[str, object]:
    context = _initial_context().model_copy(update={"execution_mode": ExecutionMode.ASSISTED})
    report = _passed_review(ResourceType.LECTURE)
    node_input = HumanReviewInput(
        task_id=TASK_ID,
        context=context,
        review_reports=[report],
        allowed_decisions=list(HumanDecision),
    )
    node_output = HumanReviewOutput(
        task_id=TASK_ID,
        decision=HumanDecision.APPROVE,
        review_comment="人工核对来源后批准。",
        operator_id="admin_demo",
        reviewed_at=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        task_decision=TaskDecision.COMPLETED,
    )
    return {"human_review": {"input": node_input, "output": node_output}}


def dump_example(value):
    if isinstance(value, dict):
        return {key: dump_example(item) for key, item in value.items()}
    if isinstance(value, list):
        return [dump_example(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
