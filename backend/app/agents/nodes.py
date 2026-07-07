from typing import Any

from app.agents.profile_agent import PROFILE_AGENT_NAME, ProfileAnalysisAgent
from app.agents.state import AgentGraphState
from app.core.compatibility import AGENT_CONTRACT_VERSION
from app.rag.embeddings import embed_texts
from app.rag.vector_store import VectorStore


def append_trace(state: AgentGraphState, agent_name: str, status: str, output: dict) -> None:
    state.setdefault("agent_trace", [])
    state["agent_trace"].append(
        {
            "agent_name": agent_name,
            "status": status,
            "output": output,
        }
    )


def _display_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if repaired else value


def _apply_profile_payload(state: AgentGraphState, payload: dict[str, Any]) -> None:
    state["profile_id"] = payload.get("profile_id") or state.get("profile_id", "")
    state["profile_result"] = payload
    state["profile"] = {
        **(payload.get("ability_profile") or {}),
        "profile_id": payload.get("profile_id"),
        "profile_type": payload.get("profile_type", "beginner"),
        "weak_knowledge": payload.get("weak_knowledge", []),
        "learning_path_id": payload.get("learning_path_id"),
    }


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


def _weakness_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    evidence = item.get("evidence") or {}
    return (
        -int(item.get("weakness_level") or 0),
        -int(evidence.get("wrong_count") or 0),
        str(item.get("name") or ""),
    )


def _target_difficulty(profile_type: str) -> int:
    if profile_type == "advanced":
        return 4
    if profile_type in {"intermediate", "practice_oriented"}:
        return 3
    return 2


def _retrieval_strategy(profile_type: str, weak_items: list[dict[str, Any]]) -> str:
    if weak_items:
        max_weakness_level = max(int(item.get("weakness_level") or 0) for item in weak_items)
        if profile_type == "beginner" or max_weakness_level >= 4:
            return "remedial"
        return "consolidation"
    if profile_type == "advanced":
        return "challenge"
    return "consolidation"


def build_retrieval_plan(payload: dict[str, Any], learning_goal: str) -> dict[str, Any]:
    profile_type = payload.get("profile_type") or "beginner"
    weak_items = sorted(
        [item for item in payload.get("weak_knowledge", []) if isinstance(item, dict)],
        key=_weakness_sort_key,
    )
    strategy = _retrieval_strategy(profile_type, weak_items)
    priority_knowledge_ids = _unique_non_empty(
        [item.get("knowledge_id") for item in weak_items[:8]]
    )
    prerequisite_knowledge_ids = _unique_non_empty(
        [
            prerequisite
            for item in weak_items
            for prerequisite in (item.get("prerequisites") or [])
        ]
    )
    weakness_summary = [
        {
            "knowledge_id": item.get("knowledge_id"),
            "name": item.get("name"),
            "category": item.get("category"),
            "weakness_level": item.get("weakness_level"),
            "weakness_type": item.get("weakness_type"),
            "suggested_action": item.get("suggested_action"),
        }
        for item in weak_items[:8]
    ]
    strategy_terms = {
        "remedial": "补救讲解",
        "consolidation": "巩固练习",
        "challenge": "挑战任务",
    }
    query_terms = _unique_non_empty(
        [
            learning_goal,
            strategy_terms[strategy],
            *[
                part
                for item in weak_items[:8]
                for part in (item.get("name"), item.get("category"), item.get("knowledge_id"))
            ],
            *prerequisite_knowledge_ids,
        ]
    )
    return {
        "profile_id": payload.get("profile_id"),
        "profile_type": profile_type,
        "strategy": strategy,
        "target_difficulty": _target_difficulty(profile_type),
        "priority_knowledge_ids": priority_knowledge_ids,
        "prerequisite_knowledge_ids": prerequisite_knowledge_ids,
        "query_terms": query_terms,
        "weakness_summary": weakness_summary,
        "n_results": 8 if strategy == "remedial" else 5,
    }


def _used_for_strategy(strategy: str) -> str:
    if strategy == "remedial":
        return "remedial_explanation"
    if strategy == "challenge":
        return "challenge_task"
    return "consolidation_practice"


def _matched_plan(knowledge_id: Any, retrieval_plan: dict[str, Any]) -> str:
    knowledge_id_text = str(knowledge_id or "")
    if knowledge_id_text in set(retrieval_plan.get("priority_knowledge_ids") or []):
        return "priority"
    if knowledge_id_text in set(retrieval_plan.get("prerequisite_knowledge_ids") or []):
        return "prerequisite"
    return "semantic"


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


def load_profile(state: AgentGraphState) -> AgentGraphState:
    state["contract_version"] = AGENT_CONTRACT_VERSION
    payload = ProfileAnalysisAgent().execute(state)
    _apply_profile_payload(state, payload)
    retrieval_plan = build_retrieval_plan(payload, state.get("learning_goal", ""))
    state["retrieval_plan"] = retrieval_plan
    append_trace(
        state,
        PROFILE_AGENT_NAME,
        "completed",
        {
            "profile_id": payload.get("profile_id"),
            "profile_type": payload.get("profile_type", "beginner"),
            "learning_path_id": payload.get("learning_path_id"),
            "profile_source": payload.get("profile_source"),
            "weak_knowledge_count": len(payload.get("weak_knowledge", [])),
            "strategy": retrieval_plan["strategy"],
            "target_difficulty": retrieval_plan["target_difficulty"],
            "priority_knowledge_count": len(retrieval_plan["priority_knowledge_ids"]),
            "prerequisite_count": len(retrieval_plan["prerequisite_knowledge_ids"]),
        },
    )
    return state


def _weak_item_text(item: Any) -> str:
    if isinstance(item, dict):
        return f"{item.get('name', '')} {item.get('category', '')} {item.get('knowledge_id', '')}"
    return str(item)


def retrieve_knowledge(state: AgentGraphState) -> AgentGraphState:
    retrieval_plan = state.get("retrieval_plan") or {}
    revision_plan = state.get("revision_plan") or {}
    query_terms = retrieval_plan.get("query_terms") or []
    if revision_plan.get("revision_required"):
        query_terms = [*query_terms, *(revision_plan.get("query_terms") or [])]
    query_text = " ".join(str(term) for term in query_terms if str(term or "").strip()).strip()
    if not query_text:
        weak_items = state.get("profile", {}).get("weak_knowledge", [])
        query_text = " ".join(
            [
                state.get("learning_goal", ""),
                *[_weak_item_text(item) for item in weak_items],
            ]
        ).strip()
    if not query_text:
        query_text = "人工智能应用开发 个性化学习 诊断 薄弱知识"

    n_results = int(retrieval_plan.get("n_results") or 5) + int(
        revision_plan.get("n_results_boost") or 0
    )
    strategy = retrieval_plan.get("strategy") or "fallback"
    used_for = _used_for_strategy(strategy)
    vector_store = VectorStore()
    result = vector_store.query(
        domain_code=state.get("domain_code", "ai_app_dev"),
        query_embeddings=embed_texts([query_text]),
        n_results=n_results,
    )
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    state["retrieved_chunks"] = [
        {
            "chunk_id": ids[index],
            "knowledge_id": metadata.get("knowledge_id"),
            "name": _display_text(metadata.get("name")),
            "category": _display_text(metadata.get("category")),
            "difficulty": metadata.get("difficulty", 1),
            "content": _display_text(documents[index]),
            "source_title": _display_text(metadata.get("source_title", "")),
            "source_url": metadata.get("source_url", ""),
            "distance": distances[index],
            "similarity": round(1 / (1 + distances[index]), 4),
            "selection_reason": f"retrieval_plan:{strategy}",
            "matched_plan": _matched_plan(metadata.get("knowledge_id"), retrieval_plan),
            "strategy": strategy,
            "target_difficulty": retrieval_plan.get("target_difficulty"),
            "used_for": used_for,
        }
        for index, metadata in enumerate(metadatas)
    ]
    matched_priority_count = sum(
        1 for item in state["retrieved_chunks"] if item.get("matched_plan") == "priority"
    )
    matched_prerequisite_count = sum(
        1 for item in state["retrieved_chunks"] if item.get("matched_plan") == "prerequisite"
    )
    semantic_count = sum(
        1 for item in state["retrieved_chunks"] if item.get("matched_plan") == "semantic"
    )
    append_trace(
        state,
        "knowledge_retrieval_agent",
        "completed",
        {
            "query": query_text,
            "retrieved": [item["knowledge_id"] for item in state["retrieved_chunks"]],
            "strategy": strategy,
            "target_difficulty": retrieval_plan.get("target_difficulty"),
            "priority_knowledge_ids": retrieval_plan.get("priority_knowledge_ids", []),
            "prerequisite_knowledge_ids": retrieval_plan.get("prerequisite_knowledge_ids", []),
            "matched_priority_count": matched_priority_count,
            "matched_prerequisite_count": matched_prerequisite_count,
            "semantic_count": semantic_count,
            "revision_required": bool(revision_plan.get("revision_required")),
            "revision_query_terms": revision_plan.get("query_terms", []),
        },
    )
    return state


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
            "- 只做功能，不检查反馈和评审。\n\n"
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


def generate_resource(state: AgentGraphState) -> AgentGraphState:
    generation_context = build_generation_context(state)
    state["generation_context"] = generation_context
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
    state["draft_resources"] = drafts
    append_trace(
        state,
        "content_generation_agent",
        "completed",
        {
            "resource_count": len(drafts),
            "generated_resource_count": len(generation_context["resource_types"]),
            "preserved_resource_count": len(state.get("passed_resources", [])),
            "resource_types": generation_context["resource_types"],
            "strategy": requirements["strategy"],
            "difficulty": requirements["difficulty"],
            "source_count": len(sources),
            "revision_required": bool(revision_plan.get("revision_required")),
        },
    )
    return state


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


def review_resource(state: AgentGraphState) -> AgentGraphState:
    generation_context = state.get("generation_context") or build_generation_context(state)
    reports = []
    for draft in state.get("draft_resources", []):
        reports.append(review_draft_resource(draft, generation_context))
    state["review_reports"] = reports or [
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
    revision_required_count = sum(
        1 for report in state["review_reports"] if report.get("revision_required")
    )
    failed_count = sum(
        1 for report in state["review_reports"] if report.get("failure_level") == "failed"
    )
    append_trace(
        state,
        "review_validation_agent",
        "completed",
        {
            "passed": all(report.get("passed") for report in state["review_reports"]),
            "report_count": len(state["review_reports"]),
            "revision_required_count": revision_required_count,
            "failed_count": failed_count,
            "average_score": round(
                sum(report.get("overall_score", 0) for report in state["review_reports"])
                / max(1, len(state["review_reports"])),
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
                for report in state["review_reports"]
            ],
        },
    )
    return state


def decide_next_step(state: AgentGraphState) -> AgentGraphState:
    reports = state.get("review_reports", [])
    if reports and all(report.get("passed") for report in reports):
        state["decision"] = "passed"
        state["revision_plan"] = {}
    elif any(report.get("failure_level") == "failed" for report in reports):
        state["decision"] = "failed"
        state["revision_plan"] = {}
    elif state.get("revision_count", 0) < 2:
        state["decision"] = "revision_required"
        state["revision_count"] = state.get("revision_count", 0) + 1
        generation_context = state.get("generation_context") or build_generation_context(state)
        generation_context = {
            **generation_context,
            "revision_count": state["revision_count"],
        }
        state["revision_plan"] = build_revision_plan(reports, generation_context)
        state["passed_resources"] = [
            draft
            for draft in state.get("draft_resources", [])
            if any(
                report.get("resource_type") == draft.get("resource_type")
                and report.get("passed")
                for report in reports
            )
        ]
    else:
        state["decision"] = "failed"
        state["revision_plan"] = {}
    append_trace(
        state,
        "orchestrator_agent",
        "completed",
        {
            "decision": state["decision"],
            "revision_count": state.get("revision_count", 0),
            "revision_resource_types": (state.get("revision_plan") or {}).get(
                "revision_resource_types", []
            ),
            "missing_requirements": (state.get("revision_plan") or {}).get(
                "missing_requirements", []
            ),
            "preserved_resource_count": len(state.get("passed_resources", [])),
        },
    )
    return state


def persist_resource(state: AgentGraphState) -> AgentGraphState:
    append_trace(
        state,
        "orchestrator_agent",
        "completed",
        {
            "next_step": "persist_resource",
            "resource_count": len(state.get("draft_resources", [])),
            "persisted_resources": len(state.get("draft_resources", [])),
        },
    )
    return state


def route_after_decision(state: AgentGraphState) -> str:
    if state["decision"] == "passed":
        return "persist_resource"
    if state["decision"] == "revision_required" and state["revision_count"] <= 2:
        return "retrieve_knowledge"
    return "end"
