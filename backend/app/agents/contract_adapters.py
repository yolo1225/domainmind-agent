from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar, cast

from app.agents.contracts import (
    AnalyzeProfileInput,
    AnalyzeProfileOutput,
    FinalizeTaskInput,
    FinalizeTaskOutput,
    CONTRACT_VERSION,
    GenerateResourceInput,
    GenerateResourceOutput,
    GenerationRequirements,
    GenerationStrategy,
    GradedQuizContent,
    HumanDecision,
    HumanReviewInput,
    HumanReviewOutput,
    InterpretFeedbackInput,
    InterpretFeedbackOutput,
    LectureContent,
    PracticeGuideContent,
    PrepareTaskInput,
    PrepareTaskOutput,
    RetrieveKnowledgeInput,
    RetrieveKnowledgeOutput,
    RetrievalPurpose,
    ReviewResourceInput,
    ReviewResourceOutput,
    SourceRef,
    StructuredResourceContent,
    TaskContext,
)
from app.agents.state import AgentGraphState


STATE_FIELD_OWNERS: dict[str, str] = {
    "prepare_task": "prepare_task",
    "interpret_feedback": "interpret_feedback",
    "analyze_profile": "analyze_profile",
    "retrieve_knowledge": "retrieve_knowledge",
    "generate_resource": "generate_resource",
    "review_resource": "review_resource",
    "finalize_task": "finalize_task",
    "human_review": "human_review",
}

def _required(state: AgentGraphState, key: str):
    value = state.get(key)  # type: ignore[literal-required]
    if value is None:
        raise ValueError(f"V2 state requires '{key}' before this node")
    return value


def _context(state: AgentGraphState) -> TaskContext:
    prepared = _required(state, "prepare_task")
    return prepared.context


def _purpose(strategy: GenerationStrategy) -> RetrievalPurpose:
    return {
        GenerationStrategy.REMEDIAL: RetrievalPurpose.REMEDIAL_EXPLANATION,
        GenerationStrategy.CONSOLIDATION: RetrievalPurpose.CONSOLIDATION_PRACTICE,
        GenerationStrategy.CHALLENGE: RetrievalPurpose.CHALLENGE_TASK,
    }[strategy]


def build_prepare_task_input(state: AgentGraphState) -> PrepareTaskInput:
    request = _required(state, "task_request")
    return PrepareTaskInput(task_id=request.task_id, request=request)


def build_interpret_feedback_input(state: AgentGraphState) -> InterpretFeedbackInput:
    context = _context(state)
    return InterpretFeedbackInput(
        task_id=context.task_id,
        context=context,
        profile=_required(state, "current_profile"),
        feedback=_required(state, "feedback_context"),
    )


def build_analyze_profile_input(state: AgentGraphState) -> AnalyzeProfileInput:
    context = _context(state)
    tutoring = state.get("interpret_feedback")
    return AnalyzeProfileInput(
        task_id=context.task_id,
        context=context,
        current_profile=_required(state, "current_profile"),
        diagnostic_summary=state.get("diagnostic_summary"),
        feedback_evidence=tutoring.evidence if tutoring else [],
        recommended_action=tutoring.recommended_action if tutoring else None,
    )


def build_retrieve_knowledge_input(state: AgentGraphState) -> RetrieveKnowledgeInput:
    context = _context(state)
    analysis = _required(state, "analyze_profile")
    return RetrieveKnowledgeInput(
        task_id=context.task_id,
        context=context,
        profile=analysis.profile,
        retrieval_plan=analysis.retrieval_plan,
        revision_plan=state.get("revision_plan"),
        purpose=_purpose(analysis.retrieval_plan.strategy),
    )


def _generation_requirements(state: AgentGraphState) -> GenerationRequirements:
    analysis = _required(state, "analyze_profile")
    retrieval = _required(state, "retrieve_knowledge")
    plan = analysis.retrieval_plan
    required_ids = list(
        dict.fromkeys([*plan.priority_knowledge_ids, *plan.prerequisite_knowledge_ids])
    )
    if not required_ids:
        required_ids = list(retrieval.covered_knowledge_ids)
    source_ids = list(dict.fromkeys(chunk.source.source_ref_id for chunk in retrieval.chunks))
    if not required_ids:
        raise ValueError("generation requires at least one target knowledge id")
    if not source_ids:
        raise ValueError("generation requires at least one retrieved source")
    return GenerationRequirements(
        resource_types=plan.resource_types,
        target_difficulty=plan.target_difficulty,
        strategy=plan.strategy,
        required_knowledge_ids=required_ids,
        source_whitelist=source_ids,
        adaptation_notes=[analysis.decision_reason],
        revision_plan=state.get("revision_plan"),
    )


def build_generate_resource_input(state: AgentGraphState) -> GenerateResourceInput:
    context = _context(state)
    analysis = _required(state, "analyze_profile")
    retrieval = _required(state, "retrieve_knowledge")
    return GenerateResourceInput(
        task_id=context.task_id,
        context=context,
        profile=analysis.profile,
        retrieved_chunks=retrieval.chunks,
        requirements=_generation_requirements(state),
    )


def build_review_resource_input(state: AgentGraphState) -> ReviewResourceInput:
    context = _context(state)
    generation = _required(state, "generate_resource")
    retrieval = _required(state, "retrieve_knowledge")
    return ReviewResourceInput(
        task_id=context.task_id,
        context=context,
        resources=generation.resources,
        requirements=_generation_requirements(state),
        evidence=retrieval.chunks,
    )


def build_finalize_task_input(state: AgentGraphState) -> FinalizeTaskInput:
    context = _context(state)
    generation = state.get("generate_resource")
    review = state.get("review_resource")
    human_review = state.get("human_review")
    revision_plan = state.get("revision_plan")
    return FinalizeTaskInput(
        task_id=context.task_id,
        context=context,
        resources=generation.resources if generation else [],
        review_reports=review.reports if review else [],
        revision_count=revision_plan.revision_count if revision_plan else 0,
        tutoring_result=state.get("interpret_feedback"),
        human_decision=human_review.decision if human_review else None,
    )


def build_human_review_input(state: AgentGraphState) -> HumanReviewInput:
    context = _context(state)
    review = _required(state, "review_resource")
    return HumanReviewInput(
        task_id=context.task_id,
        context=context,
        review_reports=review.reports,
        allowed_decisions=list(HumanDecision),
    )


OutputT = TypeVar(
    "OutputT",
    PrepareTaskOutput,
    InterpretFeedbackOutput,
    AnalyzeProfileOutput,
    RetrieveKnowledgeOutput,
    GenerateResourceOutput,
    ReviewResourceOutput,
    FinalizeTaskOutput,
    HumanReviewOutput,
)


def _output_patch(node_name: str, output: OutputT) -> AgentGraphState:
    expected_field = STATE_FIELD_OWNERS.get(node_name)
    if expected_field is None:
        raise ValueError(f"unknown V2 node '{node_name}'")
    if output.contract_version != CONTRACT_VERSION:
        raise ValueError("output contract version does not match frozen V2")
    return cast(AgentGraphState, {expected_field: output})


def prepare_task_output_to_patch(output: PrepareTaskOutput) -> AgentGraphState:
    if output.task_id != output.context.task_id:
        raise ValueError("prepare output task_id must match context.task_id")
    return _output_patch("prepare_task", output)


def interpret_feedback_output_to_patch(output: InterpretFeedbackOutput) -> AgentGraphState:
    return _output_patch("interpret_feedback", output)


def analyze_profile_output_to_patch(output: AnalyzeProfileOutput) -> AgentGraphState:
    return _output_patch("analyze_profile", output)


def retrieve_knowledge_output_to_patch(output: RetrieveKnowledgeOutput) -> AgentGraphState:
    return _output_patch("retrieve_knowledge", output)


def generate_resource_output_to_patch(
    node_input: GenerateResourceInput,
    output: GenerateResourceOutput,
) -> AgentGraphState:
    if node_input.task_id != output.task_id:
        raise ValueError("generation input and output task_id must match")
    requested = set(node_input.requirements.resource_types)
    actual = {resource.resource_type for resource in output.resources}
    if actual != requested:
        raise ValueError("generation output must contain exactly the requested resource types")
    source_whitelist = set(node_input.requirements.source_whitelist)
    for artifact in output.resources:
        actual_sources = {source.source_ref_id for source in artifact.source_refs}
        if not actual_sources.issubset(source_whitelist):
            raise ValueError("generated resources may only cite whitelisted sources")
        expected_markdown = render_resource_markdown(
            artifact.structured_content, artifact.source_refs
        )
        if artifact.content_md != expected_markdown:
            raise ValueError("content_md must be the deterministic rendering of structured_content")
    return _output_patch("generate_resource", output)


def review_resource_output_to_patch(
    node_input: ReviewResourceInput,
    output: ReviewResourceOutput,
) -> AgentGraphState:
    if node_input.task_id != output.task_id:
        raise ValueError("review input and output task_id must match")
    expected_types = {resource.resource_type for resource in node_input.resources}
    actual_types = {report.resource_type for report in output.reports}
    if actual_types != expected_types:
        raise ValueError("review output must cover exactly the submitted resource types")
    return _output_patch("review_resource", output)


def finalize_task_output_to_patch(output: FinalizeTaskOutput) -> AgentGraphState:
    return _output_patch("finalize_task", output)


def human_review_output_to_patch(output: HumanReviewOutput) -> AgentGraphState:
    return _output_patch("human_review", output)


def validate_state_patch(node_name: str, patch: Mapping[str, object]) -> None:
    expected = STATE_FIELD_OWNERS.get(node_name)
    if expected is None:
        raise ValueError(f"unknown V2 node '{node_name}'")
    unexpected = set(patch) - {expected}
    if unexpected:
        raise ValueError(f"node '{node_name}' cannot write state fields: {sorted(unexpected)}")
    if expected not in patch:
        raise ValueError(f"node '{node_name}' must write its owned field '{expected}'")


def _source_lines(source_refs: list[SourceRef]) -> list[str]:
    return [
        f"- [{source.source_ref_id}] {source.source_title} ({source.license_note})"
        for source in source_refs
    ]


def render_resource_markdown(
    content: StructuredResourceContent,
    source_refs: list[SourceRef],
) -> str:
    if isinstance(content, LectureContent):
        lines = [
            f"# {content.title}",
            "",
            "## 适配对象",
            content.target_audience,
            "",
            "## 学习目标",
            *[f"- {item}" for item in content.learning_objectives],
            "",
            "## 前置知识",
            *([f"- {item}" for item in content.prerequisite_knowledge] or ["- 无"]),
            "",
            "## 核心概念",
        ]
        for concept in content.core_concepts:
            lines.extend([f"### {concept.title}", concept.explanation])
            if concept.example:
                lines.extend(["", f"示例：{concept.example}"])
            lines.extend(["", f"来源：{', '.join(concept.source_ref_ids)}", ""])
        lines.append("## 常见误区")
        if content.misconceptions:
            for item in content.misconceptions:
                lines.extend(
                    [
                        f"- 误区：{item.misconception}",
                        f"  纠正：{item.correction}",
                        f"  来源：{', '.join(item.source_ref_ids)}",
                    ]
                )
        else:
            lines.append("- 无")
        lines.extend(["", "## 小结", content.summary])
    elif isinstance(content, PracticeGuideContent):
        lines = [
            f"# {content.title}",
            "",
            "## 适配对象",
            content.target_audience,
            "",
            "## 学习目标",
            *[f"- {item}" for item in content.learning_objectives],
            "",
            "## 环境准备",
            *[f"- {item}" for item in content.environment_requirements],
            "",
            "## 操作步骤",
        ]
        for step in sorted(content.steps, key=lambda item: item.order):
            lines.extend([f"### {step.order}. {step.title}", step.instruction])
            if step.code_or_command:
                lines.extend(["", "```text", step.code_or_command, "```"])
            lines.extend(["", f"预期结果：{step.expected_result}"])
            if step.troubleshooting:
                lines.append(f"排错：{step.troubleshooting}")
            lines.extend([f"来源：{', '.join(step.source_ref_ids)}", ""])
        lines.extend(
            [
                "## 验收标准",
                *[f"- {item}" for item in content.acceptance_criteria],
            ]
        )
    elif isinstance(content, GradedQuizContent):
        labels = {
            "foundation": "基础巩固",
            "improvement": "能力提升",
            "challenge": "挑战突破",
        }
        lines = [
            f"# {content.title}",
            "",
            "## 适配对象",
            content.target_audience,
            "",
            "## 学习目标",
            *[f"- {item}" for item in content.learning_objectives],
        ]
        for level in ("foundation", "improvement", "challenge"):
            lines.extend(["", f"## {labels[level]}"])
            questions = [item for item in content.questions if item.level.value == level]
            for question in questions:
                lines.extend(["", f"### {question.question_id}", question.prompt])
                lines.extend(f"- {option}" for option in question.options)
                lines.extend(
                    [
                        f"参考答案：{question.correct_answer}",
                        f"解析：{question.explanation}",
                        f"知识点：{question.knowledge_id}",
                        f"来源：{', '.join(question.source_ref_ids)}",
                    ]
                )
    else:  # pragma: no cover - the discriminated union prevents this branch
        raise TypeError(f"unsupported resource content: {type(content)!r}")

    lines.extend(["", "## 知识来源", *_source_lines(source_refs)])
    return "\n".join(lines).strip() + "\n"
