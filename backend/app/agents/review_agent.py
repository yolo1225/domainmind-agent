from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.agents.base import BaseAgent, PromptBudget
from app.agents.contracts import AgentMessage, ModelReview, ReviewOutput
from app.agents.generation_agent import build_generation_context
from app.agents.state import AgentGraphState
from app.core.config import settings
from app.services.llm_service import gateway
from app.services.llm_service import ModelConfigurationError


REVIEW_AGENT_NAME = "review_validation_agent"
FACTUAL_THRESHOLD = 90
SOURCE_THRESHOLD = 90
DIFFICULTY_THRESHOLD = 85
COVERAGE_THRESHOLD = 90


def _contains_any(content: str, values: list[Any]) -> bool:
    lowered = content.lower()
    return any(str(value or "").strip().lower() in lowered for value in values if value)


def _fixture_scores(
    draft: dict[str, Any],
    context: dict[str, Any],
    role: str,
    conflict_mode: str | None,
    recheck: bool,
) -> dict[str, Any]:
    sources = context.get("sources") or []
    draft_sources = draft.get("sources") or []
    candidates = [
        value
        for item in [*draft_sources, *sources]
        for value in (item.get("knowledge_id"), item.get("name"))
        if value
    ]
    source_score = 95 if draft_sources and _contains_any(draft.get("content", ""), candidates) else 0
    factual_score = 95 if source_score >= 90 else 45
    expected = int((context.get("generation_requirements") or {}).get("difficulty") or 1)
    actual = int(draft.get("difficulty") or 0)
    difficulty_score = 95 if actual == expected else 75 if abs(actual - expected) == 1 else 45
    content = draft.get("content", "")
    strategy = (context.get("generation_requirements") or {}).get("strategy")
    if strategy == "challenge":
        coverage_ok = "挑战" in content and "扩展问题" in content
    elif strategy == "remedial":
        coverage_ok = "前置知识" in content or "补救讲解" in content
    else:
        coverage_ok = "巩固" in content or "知识串联" in content
    coverage_score = 92 if coverage_ok else 70

    if conflict_mode and role == "secondary_review_model":
        if conflict_mode == "persistent" or not recheck:
            factual_score = max(40, factual_score - 25)
            source_score = max(40, source_score - 25)
    passed = (
        factual_score >= FACTUAL_THRESHOLD
        and source_score >= SOURCE_THRESHOLD
        and difficulty_score >= DIFFICULTY_THRESHOLD
        and coverage_score >= COVERAGE_THRESHOLD
    )
    fact_checks = [
        {
            "claim": f"资源引用知识来源 {candidate}",
            "supported": source_score >= 90,
            "source_ids": [str(candidate)] if source_score >= 90 else [],
            "reason": "fixture source trace check",
            "determinable": True,
        }
        for candidate in candidates[:4]
    ]
    if not fact_checks:
        fact_checks = [
            {
                "claim": "资源未提供可核验来源",
                "supported": False,
                "source_ids": [],
                "reason": "missing source",
                "determinable": True,
            }
        ]
    return {
        "model_role": role,
        "factual_score": factual_score,
        "source_trace_score": source_score,
        "difficulty_match_score": difficulty_score,
        "coverage_score": coverage_score,
        "passed": passed,
        "issues": [] if passed else ["资源未达到全部质量阈值"],
        "evidence_refs": [str(item) for item in candidates[:8]],
        "fact_checks": fact_checks,
        "unsupported_claims": [
            item["claim"] for item in fact_checks if item["supported"] is False
        ],
        "verified_claim_count": sum(1 for item in fact_checks if item["supported"] is True),
        "source_coverage": source_score,
        "unable_to_determine": [],
        "provider_mode": "fixture",
    }


def _model_payload(draft: dict[str, Any], context: dict[str, Any], *, recheck: bool) -> dict[str, Any]:
    return {
        "resource": {
            "resource_type": draft.get("resource_type"),
            "difficulty": draft.get("difficulty"),
            "content": draft.get("content", ""),
            "sources": draft.get("sources", []),
        },
        "learner_profile": context.get("profile", {}),
        "target_requirements": context.get("generation_requirements", {}),
        "retrieved_sources": context.get("sources", []),
        "recheck_after_retrieval": recheck,
        "output_schema": ModelReview.model_json_schema(),
    }


def _average(review: ModelReview) -> float:
    return sum(
        (
            review.factual_score,
            review.source_trace_score,
            review.difficulty_match_score,
            review.coverage_score,
        )
    ) / 4


class ReviewValidationAgent(BaseAgent):
    name = REVIEW_AGENT_NAME
    system_prompt_path = "app/agents/prompts/review_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {"agent_name": self.name, "status": "ready", "payload_keys": sorted(message.payload)}

    def _call_channel(
        self,
        *,
        role: str,
        model: str | None,
        draft: dict[str, Any],
        context: dict[str, Any],
        conflict_mode: str | None,
        recheck: bool,
    ) -> tuple[ModelReview, dict[str, Any]]:
        payload = _model_payload(draft, context, recheck=recheck)
        budget = PromptBudget(10_000, 3_000).validate(str(payload))
        result, metadata = gateway.complete_json(
            model=model,
            system_prompt=self.system_prompt(),
            payload=payload,
            fixture_factory=lambda: _fixture_scores(draft, context, role, conflict_mode, recheck),
            response_model=ModelReview,
        )
        result["model_role"] = role
        result["provider_mode"] = metadata["provider_mode"]
        return ModelReview.model_validate(result), {**metadata, "model_role": role, "budget": budget}

    def _review_pair(
        self,
        draft: dict[str, Any],
        context: dict[str, Any],
        conflict_mode: str | None,
        *,
        recheck: bool,
    ) -> tuple[ModelReview, ModelReview, list[dict[str, Any]]]:
        if (
            not settings.allow_fixture_llm
            and settings.primary_review_model == settings.secondary_review_model
        ):
            raise ModelConfigurationError(
                "PRIMARY_REVIEW_MODEL and SECONDARY_REVIEW_MODEL must be different"
            )
        calls = (
            ("primary_review_model", settings.primary_review_model),
            ("secondary_review_model", settings.secondary_review_model),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    self._call_channel,
                    role=role,
                    model=model,
                    draft=draft,
                    context=context,
                    conflict_mode=conflict_mode,
                    recheck=recheck,
                )
                for role, model in calls
            ]
            results = [future.result() for future in futures]
        return results[0][0], results[1][0], [results[0][1], results[1][1]]

    def execute(self, state: AgentGraphState) -> dict[str, Any]:
        context = state.get("generation_context") or build_generation_context(state)
        conflict_mode = state.get("force_review_conflict")
        reports: list[dict[str, Any]] = []
        all_model_calls: list[dict[str, Any]] = []

        for draft in state.get("draft_resources", []):
            primary, secondary, calls = self._review_pair(
                draft, context, conflict_mode, recheck=False
            )
            all_model_calls.extend(calls)
            disagreement = abs(_average(primary) - _average(secondary)) > 10 or (
                primary.passed != secondary.passed
            )
            arbitration: dict[str, Any] = {
                "required": disagreement,
                "initial_scores": {
                    "primary": primary.model_dump(),
                    "secondary": secondary.model_dump(),
                },
                "retrieved_evidence_refs": [],
                "recheck_scores": None,
            }
            final_primary, final_secondary = primary, secondary
            if disagreement:
                arbitration["action"] = "retrieve_sources_and_recheck"
                arbitration["retrieved_evidence_refs"] = [
                    item.get("knowledge_id") for item in context.get("sources", [])
                ]
                final_primary, final_secondary, recheck_calls = self._review_pair(
                    draft, context, conflict_mode, recheck=True
                )
                all_model_calls.extend(recheck_calls)
                arbitration["recheck_scores"] = {
                    "primary": final_primary.model_dump(),
                    "secondary": final_secondary.model_dump(),
                }

            persistent_disagreement = abs(
                _average(final_primary) - _average(final_secondary)
            ) > 10 or final_primary.passed != final_secondary.passed
            manual_review_required = disagreement and persistent_disagreement
            factual = min(final_primary.factual_score, final_secondary.factual_score)
            source = min(final_primary.source_trace_score, final_secondary.source_trace_score)
            difficulty = min(
                final_primary.difficulty_match_score, final_secondary.difficulty_match_score
            )
            coverage = min(final_primary.coverage_score, final_secondary.coverage_score)
            passed = final_primary.passed and final_secondary.passed and not manual_review_required
            failed = source == 0 or difficulty < 50
            decision = (
                "manual_review_required"
                if manual_review_required
                else "passed"
                if passed
                else "rejected"
                if failed
                else "revision_required"
            )
            reports.append(
                {
                    "resource_type": draft.get("resource_type"),
                    "factual_accuracy": factual,
                    "source_traceability": source,
                    "difficulty_match": difficulty,
                    "core_knowledge_coverage": coverage,
                    "overall_score": round((factual + source + difficulty + coverage) / 4, 1),
                    "primary_review": primary.model_dump(),
                    "secondary_review": secondary.model_dump(),
                    "arbitration": arbitration,
                    "passed": passed,
                    "manual_review_required": manual_review_required,
                    "decision": decision,
                    "revision_required": decision == "revision_required",
                    "failure_level": "failed" if failed else "revision" if not passed else "none",
                    "review_notes": [*final_primary.issues, *final_secondary.issues],
                }
            )

        if not reports:
            reports.append(
                {
                    "resource_type": None,
                    "factual_accuracy": 0,
                    "source_traceability": 0,
                    "difficulty_match": 0,
                    "core_knowledge_coverage": 0,
                    "overall_score": 0,
                    "passed": False,
                    "manual_review_required": False,
                    "decision": "rejected",
                    "revision_required": False,
                    "failure_level": "failed",
                    "review_notes": ["没有可审核的草稿资源。"],
                }
            )

        return ReviewOutput(
            review_reports=reports,
            trace={
                "passed": all(report.get("passed") for report in reports),
                "report_count": len(reports),
                "revision_required_count": sum(
                    1 for report in reports if report.get("revision_required")
                ),
                "failed_count": sum(
                    1 for report in reports if report.get("failure_level") == "failed"
                ),
                "manual_review_required": any(
                    report.get("manual_review_required") for report in reports
                ),
                "average_score": round(
                    sum(report.get("overall_score", 0) for report in reports) / len(reports), 1
                ),
                "resource_reviews": reports,
                "model_calls": all_model_calls,
            },
        ).model_dump()


def review_draft_resource(
    draft: dict[str, Any], generation_context: dict[str, Any]
) -> dict[str, Any]:
    """Compatibility helper used by focused tests."""

    output = ReviewValidationAgent().execute(
        {"draft_resources": [draft], "generation_context": generation_context}
    )
    return output["review_reports"][0]
