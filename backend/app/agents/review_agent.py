from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentMessage, ReviewOutput
from app.agents.generation_agent import build_generation_context
from app.agents.state import AgentGraphState


REVIEW_AGENT_NAME = "review_validation_agent"


def _contains_any(content: str, values: list[Any]) -> bool:
    content_lower = content.lower()
    return any(str(value or "").strip().lower() in content_lower for value in values if value)


def score_source_traceability(
    draft: dict[str, Any],
    sources: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    draft_sources = draft.get("sources") or []
    if not draft_sources:
        return 0, ["缺少知识来源，无法追溯生成依据。"]

    candidates = []
    for source in [*draft_sources, *sources]:
        candidates.extend([source.get("knowledge_id"), source.get("name")])
    if _contains_any(draft.get("content", ""), candidates):
        return 95, ["内容包含来源知识名称或 ID。"]
    return 60, ["内容有来源列表，但正文未出现来源知识名称或 ID。"]


def score_difficulty_match(
    draft: dict[str, Any],
    generation_requirements: dict[str, Any],
) -> tuple[int, list[str]]:
    expected = int(generation_requirements.get("difficulty") or 1)
    actual = int(draft.get("difficulty") or 0)
    diff = abs(actual - expected)
    if diff == 0:
        return 95, [f"难度匹配目标难度 {expected}。"]
    if diff == 1:
        return 75, [f"难度与目标难度 {expected} 相差 1，需要修订。"]
    return 45, [f"难度与目标难度 {expected} 差异过大。"]


def score_strategy_coverage(draft: dict[str, Any], strategy: str) -> tuple[int, list[str]]:
    required_terms = {
        "remedial": ["前置知识", "常见误区", "补救讲解"],
        "consolidation": ["检查点", "巩固练习", "知识串联"],
        "challenge": ["挑战任务", "扩展问题", "扩展边界"],
    }
    terms = required_terms.get(strategy, required_terms["consolidation"])
    content = draft.get("content", "")
    matched_terms = [term for term in terms if term in content]
    if len(matched_terms) >= 2:
        return 90, [f"策略关键词覆盖充分：{', '.join(matched_terms)}。"]
    return 70, [f"策略关键词覆盖不足，仅命中：{', '.join(matched_terms) or '无'}。"]


def review_draft_resource(
    draft: dict[str, Any],
    generation_context: dict[str, Any],
) -> dict[str, Any]:
    sources = generation_context.get("sources") or []
    requirements = generation_context.get("generation_requirements") or {}
    strategy = requirements.get("strategy") or "consolidation"

    source_traceability, source_notes = score_source_traceability(draft, sources)
    difficulty_match, difficulty_notes = score_difficulty_match(draft, requirements)
    coverage_score, coverage_notes = score_strategy_coverage(draft, strategy)
    factual_accuracy = 90 if source_traceability >= 80 else 55

    revision_required = source_traceability < 80 or difficulty_match < 80 or coverage_score < 80
    failure_level = "none"
    if source_traceability == 0 or difficulty_match < 50:
        failure_level = "failed"
    elif revision_required:
        failure_level = "revision"

    scores = [factual_accuracy, source_traceability, difficulty_match, coverage_score]
    overall_score = round(sum(scores) / len(scores), 1)
    passed = (
        all(score >= 80 for score in scores)
        and failure_level == "none"
        and not revision_required
    )
    review_notes = [*source_notes, *difficulty_notes, *coverage_notes]
    return {
        "resource_type": draft.get("resource_type"),
        "factual_accuracy": factual_accuracy,
        "source_traceability": source_traceability,
        "difficulty_match": difficulty_match,
        "core_knowledge_coverage": coverage_score,
        "overall_score": overall_score,
        "passed": passed,
        "revision_required": revision_required,
        "failure_level": failure_level,
        "review_notes": review_notes,
        "facts_score": factual_accuracy,
        "source_traceability_score": source_traceability,
        "difficulty_match_score": difficulty_match,
        "coverage_score": coverage_score,
    }


class ReviewValidationAgent(BaseAgent):
    name = REVIEW_AGENT_NAME
    system_prompt_path = "app/agents/prompts/review_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "agent_name": self.name,
            "status": "ready_for_stateful_execution",
            "payload_keys": sorted(message.payload.keys()),
        }

    def execute(self, state: AgentGraphState) -> dict[str, Any]:
        generation_context = state.get("generation_context") or build_generation_context(state)
        reports = [
            review_draft_resource(draft, generation_context)
            for draft in state.get("draft_resources", [])
        ] or [
            {
                "resource_type": None,
                "factual_accuracy": 0,
                "source_traceability": 0,
                "difficulty_match": 0,
                "core_knowledge_coverage": 0,
                "overall_score": 0,
                "facts_score": 0,
                "source_traceability_score": 0,
                "difficulty_match_score": 0,
                "coverage_score": 0,
                "passed": False,
                "revision_required": False,
                "failure_level": "failed",
                "review_notes": ["没有可审核的草稿资源。"],
            }
        ]
        revision_required_count = sum(1 for report in reports if report.get("revision_required"))
        failed_count = sum(1 for report in reports if report.get("failure_level") == "failed")
        return ReviewOutput(
            review_reports=reports,
            trace={
                "passed": all(report.get("passed") for report in reports),
                "report_count": len(reports),
                "revision_required_count": revision_required_count,
                "failed_count": failed_count,
                "average_score": round(
                    sum(report.get("overall_score", 0) for report in reports)
                    / max(1, len(reports)),
                    1,
                ),
                "resource_reviews": [
                    {
                        "resource_type": report.get("resource_type"),
                        "overall_score": report.get("overall_score", 0),
                        "passed": bool(report.get("passed")),
                        "revision_required": bool(report.get("revision_required")),
                        "failure_level": report.get("failure_level", "none"),
                    }
                    for report in reports
                ],
            },
        ).model_dump()
