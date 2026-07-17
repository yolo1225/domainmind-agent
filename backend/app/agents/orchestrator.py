from typing import Any

from app.agents.base import BaseAgent
from app.agents.legacy_contracts import AgentMessage, DecisionOutput
from app.agents.generation_agent import build_generation_context
from app.agents.legacy_state import AgentGraphState
from app.core.compatibility import AGENT_CONTRACT_VERSION


ORCHESTRATOR_AGENT_NAME = "orchestrator_agent"


def _unique_non_empty(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _coverage_requirements(strategy: str) -> list[str]:
    if strategy == "remedial":
        return ["前置知识", "常见误区", "补救讲解"]
    if strategy == "challenge":
        return ["挑战任务", "扩展问题", "扩展边界"]
    return ["检查点", "巩固练习", "知识串联"]


def build_revision_plan(
    review_reports: list[dict[str, Any]],
    generation_context: dict[str, Any],
) -> dict[str, Any]:
    strategy = (generation_context.get("generation_requirements") or {}).get(
        "strategy", "consolidation"
    )
    revision_resource_types: list[str] = []
    issues_by_resource_type: dict[str, list[str]] = {}
    missing_requirements: list[str] = []

    for report in review_reports:
        if report.get("passed") or report.get("failure_level") == "failed":
            continue
        resource_type = report.get("resource_type")
        if not resource_type:
            continue
        issues: list[str] = []
        if int(report.get("source_traceability") or 0) < 80:
            issues.append("source_traceability")
            missing_requirements.append("补充来源引用")
        if int(report.get("difficulty_match") or 0) < 80:
            issues.append("difficulty_match")
            missing_requirements.append("对齐目标难度")
        if int(report.get("core_knowledge_coverage") or 0) < 80:
            issues.append("strategy_coverage")
            missing_requirements.extend(_coverage_requirements(strategy))
        if int(report.get("factual_accuracy") or 0) < 80:
            issues.append("factual_accuracy")
        if issues:
            revision_resource_types.append(resource_type)
            issues_by_resource_type[resource_type] = _unique_non_empty(issues)

    missing_requirements = _unique_non_empty(missing_requirements)
    query_terms = _unique_non_empty(
        [
            *missing_requirements,
            *[
                issue
                for issues in issues_by_resource_type.values()
                for issue in issues
            ],
        ]
    )
    return {
        "revision_required": bool(revision_resource_types),
        "revision_count": int(generation_context.get("revision_count") or 0),
        "revision_resource_types": _unique_non_empty(revision_resource_types),
        "issues_by_resource_type": issues_by_resource_type,
        "missing_requirements": missing_requirements,
        "query_terms": query_terms,
        "n_results_boost": 3 if "补充来源引用" in missing_requirements else 1,
    }


class OrchestratorAgent(BaseAgent):
    name = ORCHESTRATOR_AGENT_NAME
    system_prompt_path = "app/agents/prompts/orchestrator_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "agent_name": self.name,
            "status": "ready_for_stateful_execution",
            "payload_keys": sorted(message.payload.keys()),
        }

    def decide(self, state: AgentGraphState) -> dict[str, Any]:
        reports = state.get("review_reports", [])
        revision_count = state.get("revision_count", 0)
        revision_plan: dict[str, Any] = {}
        passed_resources: list[dict[str, Any]] = state.get("passed_resources", [])

        if any(
            report.get("manual_review_required")
            or report.get("decision") == "manual_review_required"
            for report in reports
        ):
            decision = "manual_review_required"
        elif reports and all(report.get("passed") for report in reports):
            decision = "passed"
        elif any(report.get("failure_level") == "failed" for report in reports):
            decision = "failed"
        elif revision_count < 2:
            decision = "revision_required"
            revision_count += 1
            generation_context = state.get("generation_context") or build_generation_context(state)
            generation_context = {
                **generation_context,
                "revision_count": revision_count,
            }
            revision_plan = build_revision_plan(reports, generation_context)
            passed_resources = [
                draft
                for draft in state.get("draft_resources", [])
                if any(
                    report.get("resource_type") == draft.get("resource_type")
                    and report.get("passed")
                    for report in reports
                )
            ]
        else:
            decision = "failed"

        return DecisionOutput(
            decision=decision,
            revision_count=revision_count,
            revision_plan=revision_plan,
            passed_resources=passed_resources,
            trace={
                "decision": decision,
                "revision_count": revision_count,
                "revision_resource_types": revision_plan.get("revision_resource_types", []),
                "missing_requirements": revision_plan.get("missing_requirements", []),
                "preserved_resource_count": len(passed_resources),
            },
        ).model_dump()

    def persist_summary(self, state: AgentGraphState) -> dict[str, Any]:
        return {
            "next_step": "persist_resource",
            "resource_count": len(state.get("draft_resources", [])),
            "persisted_resources": len(state.get("draft_resources", [])),
        }


def create_initial_state(
    task_id: str,
    learner_id: str,
    profile_id: str,
    learning_goal: str,
) -> AgentGraphState:
    return {
        "contract_version": AGENT_CONTRACT_VERSION,
        "task_id": task_id,
        "trigger_type": "initial_generation",
        "execution_mode": "auto",
        "learner_id": learner_id,
        "profile_id": profile_id,
        "domain_code": "ai_app_dev",
        "resource_types": ["lecture", "practice_guide", "graded_quiz"],
        "learning_goal": learning_goal,
        "profile": {},
        "retrieved_chunks": [],
        "draft_resources": [],
        "review_reports": [],
        "revision_count": 0,
        "decision": "pending",
        "error_message": None,
        "profile_update_required": False,
        "profile_change_evidence": [],
        "affected_knowledge_ids": [],
        "affected_path_node_ids": [],
        "affected_resource_ids": [],
        "manual_review_required": False,
        "human_review_decision": None,
        "agent_contexts": {},
    }


def get_generation_graph():
    from app.agents.graphs import build_learning_graph

    return build_learning_graph()
