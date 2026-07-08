from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentMessage, GenerationOutput
from app.agents.state import AgentGraphState


GENERATION_AGENT_NAME = "content_generation_agent"


def _display_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if repaired else value


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


def build_generation_context(state: AgentGraphState) -> dict[str, Any]:
    profile = state.get("profile", {})
    retrieval_plan = state.get("retrieval_plan", {})
    revision_plan = state.get("revision_plan") or {}
    strategy = retrieval_plan.get("strategy") or "consolidation"
    target_difficulty = int(retrieval_plan.get("target_difficulty") or 2)
    resource_types = state.get("resource_types", [])
    if revision_plan.get("revision_required"):
        resource_types = revision_plan.get("revision_resource_types") or resource_types
    tone_by_strategy = {
        "remedial": "基础解释 + 小步练习",
        "consolidation": "知识串联 + 任务检查点",
        "challenge": "扩展边界 + 综合挑战",
    }
    ability_profile = {
        key: value
        for key, value in profile.items()
        if key not in {"profile_id", "profile_type", "weak_knowledge", "learning_path_id"}
    }
    return {
        "profile": {
            "profile_id": profile.get("profile_id") or state.get("profile_id"),
            "profile_type": profile.get("profile_type", "beginner"),
            "ability_profile": ability_profile,
            "weak_knowledge": profile.get("weak_knowledge", []),
        },
        "retrieval_plan": retrieval_plan,
        "revision_plan": revision_plan,
        "sources": state.get("retrieved_chunks", []),
        "resource_types": resource_types,
        "generation_requirements": {
            "difficulty": target_difficulty,
            "strategy": strategy,
            "must_include_sources": True,
            "tone": tone_by_strategy.get(strategy, tone_by_strategy["consolidation"]),
            "source_policy": "cite_retrieved_knowledge_only",
            "missing_requirements": revision_plan.get("missing_requirements", []),
        },
    }


def _source_lines(sources: list[dict[str, Any]]) -> str:
    return "\n".join(
        (
            f"- {_display_text(item['name'])}（{item['knowledge_id']}，"
            f"{item.get('matched_plan', 'semantic')}）：{_display_text(item.get('content', ''))}"
        )
        for item in sources
    )


def _lecture_content(
    *,
    title: str,
    profile_type: str,
    requirements: dict[str, Any],
    source_lines: str,
) -> str:
    strategy = requirements["strategy"]
    if strategy == "remedial":
        return (
            f"# 补救讲解：{title}\n\n"
            f"画像类型：{profile_type}。难度：{requirements['difficulty']}。\n\n"
            "## 前置知识\n"
            "先回到来源中的 prerequisite 与 priority 知识点，补齐概念入口。\n\n"
            "## 概念拆解\n"
            "把核心概念拆成定义、作用、输入输出和验证方式四步理解。\n\n"
            "## 常见误区\n"
            "- 只记结论，不说明来源。\n"
            "- 只做功能，不检查反馈和评估。\n\n"
            f"## 来源知识\n{source_lines}\n"
        )
    if strategy == "challenge":
        return (
            f"# 挑战任务讲义：{title}\n\n"
            f"画像类型：{profile_type}。难度：{requirements['difficulty']}。\n\n"
            "## 扩展边界\n"
            "从来源知识出发，比较基础实现、可评测实现和可复用实现的差异。\n\n"
            "## 扩展问题\n"
            "- 如何证明生成结果可靠？\n"
            "- 如何把当前能力迁移到另一个学习任务？\n\n"
            f"## 来源知识\n{source_lines}\n"
        )
    return (
        f"# 巩固练习讲义：{title}\n\n"
        f"画像类型：{profile_type}。难度：{requirements['difficulty']}。\n\n"
        "## 知识串联\n"
        "把来源知识按前置概念、核心方法、应用检查点串成一条学习链。\n\n"
        "## 巩固练习\n"
        "完成一个小型任务，并用检查点确认输入、处理、输出和反馈都可复现。\n\n"
        f"## 来源知识\n{source_lines}\n"
    )


def _practice_content(*, requirements: dict[str, Any], source_lines: str) -> str:
    strategy = requirements["strategy"]
    if strategy == "remedial":
        return (
            "# 小步实操指南\n\n"
            "## 补救讲解检查点\n"
            "1. 先复述前置知识的定义。\n"
            "2. 找到一个最小输入样例。\n"
            "3. 完成一步操作后立即记录结果。\n"
            "4. 对照来源知识检查是否遗漏关键条件。\n"
            "5. 写下一个常见误区，并说明如何避免。\n\n"
            f"## 来源知识\n{source_lines}\n"
        )
    if strategy == "challenge":
        return (
            "# 开放项目挑战任务\n\n"
            "1. 选择一个真实应用场景。\n"
            "2. 设计可追踪的输入、生成、审核和反馈链路。\n"
            "3. 给出扩展问题：如果知识库更新，系统应该如何自动调整？\n\n"
            f"## 来源知识\n{source_lines}\n"
        )
    return (
        "# 巩固练习实操指南\n\n"
        "1. 按来源知识完成一个完整任务。\n"
        "2. 写出每一步的检查点。\n"
        "3. 对比预期结果和实际结果，标记需要继续巩固的环节。\n\n"
        f"## 来源知识\n{source_lines}\n"
    )


def _quiz_content(*, title: str, requirements: dict[str, Any], source_lines: str) -> str:
    strategy = requirements["strategy"]
    if strategy == "remedial":
        question = "基础题：学习这个知识点前，为什么要先确认前置知识？"
        answer = "因为补救讲解需要先定位常见误区，前置知识决定能否理解核心概念和操作步骤。"
    elif strategy == "challenge":
        question = f"综合挑战题：如何围绕“{title}”设计一个可评测的挑战任务？"
        answer = "需要包含目标、来源、实现步骤、审核标准、反馈更新方式和扩展问题。"
    else:
        question = f"应用题：围绕“{title}”，如何设置任务检查点？"
        answer = "在知识串联后完成巩固练习，检查输入、处理过程、输出结果、来源引用和反馈动作。"
    return (
        "# 分级测验\n\n"
        f"{question}\n\n"
        f"参考答案：{answer}\n\n"
        f"## 来源知识\n{source_lines}\n"
    )


def _revision_requirement_block(requirements: dict[str, Any]) -> str:
    missing_requirements = _unique_non_empty(requirements.get("missing_requirements", []))
    if not missing_requirements:
        return ""
    lines = "\n".join(f"- {item}" for item in missing_requirements)
    return f"\n## 修订要求\n{lines}\n"


class ContentGenerationAgent(BaseAgent):
    name = GENERATION_AGENT_NAME
    system_prompt_path = "app/agents/prompts/generation_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "agent_name": self.name,
            "status": "ready_for_stateful_execution",
            "payload_keys": sorted(message.payload.keys()),
        }

    def execute(self, state: AgentGraphState) -> dict[str, Any]:
        generation_context = build_generation_context(state)
        sources = generation_context["sources"]
        requirements = generation_context["generation_requirements"]
        source_lines = _source_lines(sources)
        main_title = _display_text(sources[0]["name"]) if sources else "AI 应用开发"
        profile_type = generation_context["profile"].get("profile_type", "beginner")
        revision_plan = generation_context.get("revision_plan") or {}
        target_resource_types = set(generation_context["resource_types"])
        drafts = [
            resource
            for resource in state.get("passed_resources", [])
            if resource.get("resource_type") not in target_resource_types
        ]
        for resource_type in generation_context["resource_types"]:
            if resource_type == "lecture":
                content = _lecture_content(
                    title=main_title,
                    profile_type=profile_type,
                    requirements=requirements,
                    source_lines=source_lines,
                )
            elif resource_type == "practice_guide":
                content = _practice_content(requirements=requirements, source_lines=source_lines)
            else:
                content = _quiz_content(
                    title=main_title,
                    requirements=requirements,
                    source_lines=source_lines,
                )
            content = f"{content}{_revision_requirement_block(requirements)}"
            drafts.append(
                {
                    "resource_type": resource_type,
                    "title": f"{main_title}个性化{resource_type}",
                    "content": content,
                    "difficulty": requirements["difficulty"],
                    "sources": [
                        {
                            "knowledge_id": item["knowledge_id"],
                            "name": _display_text(item["name"]),
                            "source_title": _display_text(item.get("source_title", "")),
                            "matched_plan": item.get("matched_plan", "semantic"),
                            "used_for": item.get("used_for"),
                        }
                        for item in sources
                    ],
                }
            )
        return GenerationOutput(
            generation_context=generation_context,
            draft_resources=drafts,
            trace={
                "resource_count": len(drafts),
                "generated_resource_count": len(generation_context["resource_types"]),
                "preserved_resource_count": len(state.get("passed_resources", [])),
                "resource_types": generation_context["resource_types"],
                "strategy": requirements["strategy"],
                "difficulty": requirements["difficulty"],
                "source_count": len(sources),
                "revision_required": bool(revision_plan.get("revision_required")),
            },
        ).model_dump()
