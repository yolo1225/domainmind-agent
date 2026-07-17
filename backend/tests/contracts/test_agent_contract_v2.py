from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.contract_adapters import (
    analyze_profile_output_to_patch,
    build_analyze_profile_input,
    build_finalize_task_input,
    build_generate_resource_input,
    build_human_review_input,
    build_interpret_feedback_input,
    build_prepare_task_input,
    build_retrieve_knowledge_input,
    build_review_resource_input,
    finalize_task_output_to_patch,
    generate_resource_output_to_patch,
    human_review_output_to_patch,
    interpret_feedback_output_to_patch,
    prepare_task_output_to_patch,
    retrieve_knowledge_output_to_patch,
    review_resource_output_to_patch,
    validate_state_patch,
)
from app.agents.contract_examples import (
    PROFILE,
    agent_message_example,
    dump_example,
    feedback_flow_example,
    human_review_example,
    initial_generation_flow_example,
    resource_examples,
)
from app.agents.contracts import (
    AgentContractSchema,
    AbilityScores,
    ArbitrationResult,
    DiagnosticSummary,
    EvidenceRef,
    EvidenceType,
    ExecutionMode,
    FactCheck,
    FinalizeTaskOutput,
    GenerateResourceOutput,
    GeneratedResourceArtifact,
    HumanReviewOutput,
    PrepareTaskInput,
    ProfileSnapshot,
    ReviewReport,
    ResourceType,
    TaskDecision,
    TaskRequest,
    TriggerType,
)
from app.agents.state import AgentGraphState


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = PROJECT_ROOT / "docs" / "contracts" / "v2"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }


def test_v1_and_v2_contract_modules_are_physically_isolated() -> None:
    agent_dir = PROJECT_ROOT / "backend" / "app" / "agents"
    formal_contracts = (agent_dir / "contracts.py").read_text(encoding="utf-8")
    formal_state = (agent_dir / "state.py").read_text(encoding="utf-8")
    assert "legacy_contracts" not in formal_contracts
    assert "legacy_state" not in formal_state
    assert "app.core.compatibility" not in formal_contracts
    assert "class AgentGraphStateV2" not in formal_state
    assert "class AgentNameV2" not in formal_contracts
    assert "class MessageTypeV2" not in formal_contracts
    assert "class AgentMessageV2" not in formal_contracts

    legacy_runtime_files = [
        "base.py",
        "generation_agent.py",
        "graphs.py",
        "nodes.py",
        "orchestrator.py",
        "profile_agent.py",
        "retrieval_agent.py",
        "review_agent.py",
        "tools.py",
        "tutoring_agent.py",
    ]
    for filename in legacy_runtime_files:
        imported = _imported_modules(agent_dir / filename)
        assert "app.agents.contracts" not in imported, filename
        assert "app.agents.state" not in imported, filename

    legacy_consumers = [
        PROJECT_ROOT / "backend" / "app" / "services" / "diagnostic_service.py",
        PROJECT_ROOT / "backend" / "app" / "services" / "generation_service.py",
        PROJECT_ROOT / "backend" / "app" / "workers" / "generation_worker.py",
    ]
    for path in legacy_consumers:
        imported = _imported_modules(path)
        assert "app.agents.state" not in imported, path.name
        assert "app.agents.legacy_state" in imported, path.name


def test_v2_models_reject_unknown_fields_and_out_of_range_values() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        TaskRequest(
            task_id="task_1",
            session_id="task_1",
            trigger_type=TriggerType.INITIAL_GENERATION,
            execution_mode=ExecutionMode.AUTO,
            learner_id="learner_1",
            profile_id="profile_1",
            domain_code="ai_app_dev",
            resource_types=[ResourceType.LECTURE],
            learning_goal="RAG",
            undeclared_field=True,
        )

    with pytest.raises(ValidationError):
        AbilityScores(
            theory=101,
            practice=50,
            problem_solving=50,
            knowledge_breadth=50,
            learning_speed=50,
        )

    with pytest.raises(ValidationError):
        EvidenceRef(
            evidence_id="evidence_1",
            evidence_type=EvidenceType.QUICK_FEEDBACK,
            summary="too hard",
            confidence=1.1,
        )


def test_feedback_task_requires_resource_and_feedback_references() -> None:
    with pytest.raises(ValidationError, match="resource feedback requires"):
        TaskRequest(
            task_id="task_1",
            session_id="task_1",
            trigger_type=TriggerType.RESOURCE_FEEDBACK,
            execution_mode=ExecutionMode.AUTO,
            learner_id="learner_1",
            profile_id="profile_1",
            domain_code="ai_app_dev",
            resource_types=[ResourceType.LECTURE],
            learning_goal="RAG",
        )


def test_profile_contract_requires_all_five_ability_dimensions() -> None:
    profile = PROFILE.model_dump()
    del profile["ability_scores"]["learning_speed"]
    with pytest.raises(ValidationError):
        ProfileSnapshot.model_validate(profile)


def test_three_resource_examples_are_strict_and_complete() -> None:
    resources = resource_examples()
    assert {resource.resource_type for resource in resources} == set(ResourceType)
    assert all(resource.content_md.endswith("\n") for resource in resources)
    assert all("## 知识来源" in resource.content_md for resource in resources)
    quiz = next(item for item in resources if item.resource_type == ResourceType.GRADED_QUIZ)
    assert len(quiz.structured_content.questions) >= 6
    assert {item.level.value for item in quiz.structured_content.questions} == {
        "foundation",
        "improvement",
        "challenge",
    }


def test_initial_generation_fixture_crosses_all_automatic_nodes() -> None:
    flow = initial_generation_flow_example()
    prepare = flow["prepare_task"]
    analyze = flow["analyze_profile"]
    retrieve = flow["retrieve_knowledge"]
    generate = flow["generate_resource"]
    review = flow["review_resource"]
    finalize = flow["finalize_task"]
    state: AgentGraphState = {
        "contract_version": "agent-contract-v2",
        "task_request": prepare["input"].request,
        "current_profile": analyze["input"].current_profile,
        "diagnostic_summary": analyze["input"].diagnostic_summary,
    }

    assert build_prepare_task_input(state) == prepare["input"]
    patch = prepare_task_output_to_patch(prepare["output"])
    validate_state_patch("prepare_task", patch)
    state.update(patch)

    built_analyze = build_analyze_profile_input(state)
    assert built_analyze.context == analyze["input"].context
    patch = analyze_profile_output_to_patch(analyze["output"])
    validate_state_patch("analyze_profile", patch)
    state.update(patch)

    built_retrieve = build_retrieve_knowledge_input(state)
    assert built_retrieve.retrieval_plan == retrieve["input"].retrieval_plan
    patch = retrieve_knowledge_output_to_patch(retrieve["output"])
    validate_state_patch("retrieve_knowledge", patch)
    state.update(patch)

    built_generate = build_generate_resource_input(state)
    patch = generate_resource_output_to_patch(built_generate, generate["output"])
    validate_state_patch("generate_resource", patch)
    state.update(patch)

    built_review = build_review_resource_input(state)
    assert built_review.evidence == review["input"].evidence
    patch = review_resource_output_to_patch(built_review, review["output"])
    validate_state_patch("review_resource", patch)
    state.update(patch)

    built_finalize = build_finalize_task_input(state)
    assert built_finalize.review_reports == finalize["input"].review_reports
    patch = finalize_task_output_to_patch(finalize["output"])
    validate_state_patch("finalize_task", patch)
    state.update(patch)
    assert state["finalize_task"].decision.value == "completed"


def test_feedback_fixture_reaches_no_change_without_generation() -> None:
    flow = feedback_flow_example()
    prepare = flow["prepare_task"]
    tutoring = flow["interpret_feedback"]
    analyze = flow["analyze_profile"]
    finalize = flow["finalize_task"]
    state: AgentGraphState = {
        "contract_version": "agent-contract-v2",
        "task_request": prepare["input"].request,
        "current_profile": tutoring["input"].profile,
        "feedback_context": tutoring["input"].feedback,
    }
    state.update(prepare_task_output_to_patch(prepare["output"]))

    assert build_interpret_feedback_input(state) == tutoring["input"]
    state.update(interpret_feedback_output_to_patch(tutoring["output"]))
    built_analyze = build_analyze_profile_input(state)
    assert built_analyze.feedback_evidence == tutoring["output"].evidence
    state.update(analyze_profile_output_to_patch(analyze["output"]))
    built_finalize = build_finalize_task_input(state)
    assert built_finalize.tutoring_result == finalize["input"].tutoring_result
    state.update(finalize_task_output_to_patch(finalize["output"]))
    assert state["finalize_task"].decision.value == "no_change"


def test_human_review_contract_has_a_dedicated_state_patch() -> None:
    initial = initial_generation_flow_example()
    human = human_review_example()["human_review"]
    state: AgentGraphState = {
        "contract_version": "agent-contract-v2",
        "prepare_task": initial["prepare_task"]["output"],
        "review_resource": initial["review_resource"]["output"],
    }
    built = build_human_review_input(state)
    assert built.allowed_decisions == human["input"].allowed_decisions
    patch = human_review_output_to_patch(human["output"])
    validate_state_patch("human_review", patch)


def test_state_owner_rejects_cross_node_writes() -> None:
    with pytest.raises(ValueError, match="cannot write"):
        validate_state_patch(
            "retrieve_knowledge",
            {"retrieve_knowledge": object(), "generate_resource": object()},
        )


def test_generation_patch_rejects_non_whitelisted_source_and_markdown_drift() -> None:
    flow = initial_generation_flow_example()
    node_input = flow["generate_resource"]["input"]
    valid_output = flow["generate_resource"]["output"]
    artifact = valid_output.resources[0]
    non_matching_requirements = node_input.requirements.model_copy(
        update={"source_whitelist": ["foreign::chunk::0"]}
    )
    invalid_source_input = node_input.model_copy(
        update={"requirements": non_matching_requirements}
    )
    with pytest.raises(ValueError, match="whitelisted"):
        generate_resource_output_to_patch(invalid_source_input, valid_output)

    invalid_markdown_output = GenerateResourceOutput(
        task_id=valid_output.task_id,
        resources=[artifact.model_copy(update={"content_md": "# drift\n"})],
    )
    with pytest.raises(ValueError, match="deterministic rendering"):
        generate_resource_output_to_patch(node_input, invalid_markdown_output)


def test_cross_field_contract_invariants_reject_contradictory_states() -> None:
    flow = initial_generation_flow_example()

    prepare_payload = flow["prepare_task"]["input"].model_dump()
    prepare_payload["task_id"] = "wrong_task"
    with pytest.raises(ValidationError, match="must match request.task_id"):
        PrepareTaskInput.model_validate(prepare_payload)

    with pytest.raises(ValidationError, match="cannot exceed question_count"):
        DiagnosticSummary(
            diagnostic_session_id="diagnostic_invalid",
            question_count=5,
            answered_count=4,
            correct_count=2,
            skipped_count=2,
            score_percent=40,
        )

    artifact = flow["generate_resource"]["output"].resources[0]
    generation_input = flow["generate_resource"]["input"]
    generation_input_payload = generation_input.model_dump()
    generation_input_payload["requirements"]["source_whitelist"] = ["unretrieved::source"]
    with pytest.raises(ValidationError, match="only contain retrieved sources"):
        type(generation_input).model_validate(generation_input_payload)

    artifact_payload = artifact.model_dump()
    artifact_payload["structured_content"]["core_concepts"][0]["source_ref_ids"] = [
        "unlisted::source"
    ]
    with pytest.raises(ValidationError, match="exactly match source_refs"):
        GeneratedResourceArtifact.model_validate(artifact_payload)

    review_input = flow["review_resource"]["input"]
    review_input_payload = review_input.model_dump()
    review_input_payload["resources"].append(resource_examples()[1].model_dump())
    with pytest.raises(ValidationError, match="must match generation requirements"):
        type(review_input).model_validate(review_input_payload)

    with pytest.raises(ValidationError, match="must perform retrieval"):
        ArbitrationResult(
            required=True,
            retrieval_performed=False,
            disagreement_remains=True,
        )

    with pytest.raises(ValidationError, match="supported must be boolean"):
        FactCheck(
            claim="无法判定的声明",
            supported=True,
            reason="证据不足",
            determinable=False,
        )

    report = flow["review_resource"]["output"].reports[0]
    report_payload = report.model_dump()
    report_payload["manual_review_required"] = True
    with pytest.raises(ValidationError, match="must match the review decision"):
        ReviewReport.model_validate(report_payload)

    finalize = flow["finalize_task"]["output"]
    finalize_payload = finalize.model_dump()
    finalize_payload["decision"] = TaskDecision.REVISION_REQUIRED
    finalize_payload["passed_resource_types"] = []
    with pytest.raises(ValidationError, match="revision plan"):
        FinalizeTaskOutput.model_validate(finalize_payload)

    human = human_review_example()["human_review"]["output"]
    human_payload = human.model_dump()
    human_payload["task_decision"] = TaskDecision.REJECTED
    with pytest.raises(ValidationError, match="must match the human decision"):
        HumanReviewOutput.model_validate(human_payload)


def test_review_patch_rejects_missing_resource_report() -> None:
    resources = resource_examples()[:2]
    flow = initial_generation_flow_example()
    node_input = flow["review_resource"]["input"].model_copy(update={"resources": resources})
    output = flow["review_resource"]["output"]
    with pytest.raises(ValueError, match="exactly the submitted resource types"):
        review_resource_output_to_patch(node_input, output)


def test_checked_in_schema_and_examples_match_executable_contracts() -> None:
    expected = {
        "agent-contract-v2.schema.json": AgentContractSchema.model_json_schema(),
        "agent-message.example.json": dump_example(agent_message_example()),
        "initial-generation.example.json": dump_example(initial_generation_flow_example()),
        "feedback-no-change.example.json": dump_example(feedback_flow_example()),
        "human-review.example.json": dump_example(human_review_example()),
        "resource-types.example.json": dump_example(resource_examples()),
    }
    for filename, payload in expected.items():
        checked_in = json.loads((ARTIFACT_DIR / filename).read_text(encoding="utf-8"))
        assert checked_in == payload, f"regenerate frozen contract artifact: {filename}"
