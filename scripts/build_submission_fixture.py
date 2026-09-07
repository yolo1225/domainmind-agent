"""Build the versioned competition fixture from the audited runtime snapshots.

The output is deliberately split into a direct bootstrap fixture and an import
demonstration source.  They represent alternative reproduction paths and must
not be loaded into the same database together.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = PROJECT_ROOT / "deliverables" / "competition-initial-review" / "07_测试数据与案例"
FIXTURE_ROOT = PROJECT_ROOT / "data" / "submission_fixtures" / "ai_app_dev_v1"
IMPORT_ROOT = PROJECT_ROOT / "deliverables" / "knowledge-import-packages" / "ai_app_dev"
FIXTURE_VERSION = "ai_app_dev_submission_fixture_v1"
PURPOSE_SLOTS = (
    ("diagnosis", "diagnosis_1", "foundation"),
    ("graded_quiz", "graded_foundation", "foundation"),
    ("graded_quiz", "graded_improvement", "improvement"),
    ("graded_quiz", "graded_challenge", "challenge"),
    ("mastery_validation", "mastery_1", "improvement"),
    ("mastery_validation", "mastery_2", "challenge"),
)

# The expanded AI fundamentals section is part of the frozen submission
# baseline. These declared course prerequisites keep every item connected to
# the active learning graph without inventing relations at runtime.
CURATED_PREREQUISITE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "ki_0e673b8eec42b320": ("ki_65f1659af27d4984",),
    "ki_185eac93556247a0": ("ki_947e73313a12fc88",),
    "ki_23ed31d7af0f95d0": ("ki_d122c91269e87257",),
    "ki_307d4cd9dc09951f": ("ki_8ba31f93fb9f7bcd",),
    "ki_3e3229243be11058": ("ki_947e73313a12fc88",),
    "ki_46d9d4de4c4835d2": ("ki_e82e51e944744bdb",),
    "ki_63bef1cdb46b2948": ("ki_46d9d4de4c4835d2",),
    "ki_65f1659af27d4984": ("ki_a23b92994c49c639",),
    "ki_6613d44b56deaa3e": ("ki_d122c91269e87257",),
    "ki_68375283ac5ca527": ("ai_app_dev_overview",),
    "ki_747302beb84cdbdf": ("ki_a23b92994c49c639",),
    "ki_747c6d2d0ed6ba38": ("ki_fc9bb9f9de5913e5",),
    "ki_8107173e3737a444": ("ki_a23b92994c49c639",),
    "ki_884cca8ccb2c9f0c": ("ki_747302beb84cdbdf",),
    "ki_8ba31f93fb9f7bcd": ("ki_65f1659af27d4984",),
    "ki_8fcfe12783a7baea": ("ki_185eac93556247a0",),
    "ki_947e73313a12fc88": ("ki_6613d44b56deaa3e",),
    "ki_96709f9830593e5c": ("ki_6613d44b56deaa3e",),
    "ki_a23b92994c49c639": ("ai_app_dev_overview",),
    "ki_d122c91269e87257": ("ki_e82e51e944744bdb",),
    "ki_e669ac1d0bc95972": ("ki_884cca8ccb2c9f0c",),
    "ki_e82e51e944744bdb": ("ki_a23b92994c49c639",),
    "ki_eb61025d0c6deea3": ("ki_185eac93556247a0",),
    "ki_f183dd3f6c58b215": ("ki_0e673b8eec42b320",),
    "ki_fc9bb9f9de5913e5": ("ki_8107173e3737a444",),
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_knowledge(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in raw_items:
        knowledge_id = str(item["knowledge_id"])
        prerequisites = list(item.get("prerequisites", []))
        for prerequisite_id in CURATED_PREREQUISITE_EXTENSIONS.get(knowledge_id, ()):
            if prerequisite_id not in prerequisites:
                prerequisites.append(prerequisite_id)
        result.append(
            {
                "knowledge_id": knowledge_id,
                "domain_code": item["domain_code"],
                "name": item["name"],
                "category": item["category"],
                "difficulty": item["difficulty"],
                "tags": item["tags"],
                "content": item["content"],
                "source_title": item["source_title"],
                "source_url": item["source_url"],
                "license_note": item["license_note"],
                "ability_weights": item["ability_weights"],
                "evidence_capabilities": item.get("evidence_capabilities", []),
                "prerequisites": prerequisites,
                "related": item.get("related", []),
            }
        )
    return sorted(result, key=lambda item: item["knowledge_id"])


def canonical_questions(raw_questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for question in raw_questions:
        answer_key = dict(question["answer_key"])
        purpose = question["purpose"]
        if answer_key.get("question_bank_uses") != [purpose]:
            raise ValueError(f"question purpose mismatch: {question['question_id']}")
        result.append(
            {
                "question_id": question["question_id"],
                "question_external_id": question["question_external_id"],
                "knowledge_id": question["knowledge_id"],
                "related_knowledge_ids": question.get("related_knowledge_ids", []),
                "question_type": question["question_type"],
                "difficulty": question["difficulty"],
                "stem": question["stem"],
                "options": question.get("options", []),
                "answer_key": answer_key,
                "status": question["status"],
            }
        )
    return sorted(result, key=lambda item: item["question_id"])


def relation_records(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    relations: list[dict[str, str]] = []
    for item in items:
        for prerequisite_id in item["prerequisites"]:
            relations.append(
                {
                    "relation_type": "prerequisite",
                    "source_knowledge_id": prerequisite_id,
                    "target_knowledge_id": item["knowledge_id"],
                }
            )
        for related_id in item["related"]:
            relations.append(
                {
                    "relation_type": "related",
                    "source_knowledge_id": item["knowledge_id"],
                    "target_knowledge_id": related_id,
                }
            )
    return sorted(
        relations,
        key=lambda item: (
            item["relation_type"],
            item["source_knowledge_id"],
            item["target_knowledge_id"],
        ),
    )


def write_full_import_markdown(items: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 人工智能应用开发实训完整知识包 (ai_app_dev)",
        "",
        "本文件用于空库导入演示，包含 75 条正式主领域知识点。请与启动夹具二选一使用。",
        "",
    ]
    for item in items:
        source_title = item["source_title"].replace("]", "\\]")
        tags = ", ".join(item["tags"])
        weights = json.dumps(item["ability_weights"], ensure_ascii=False, separators=(",", ":"))
        content = re.sub(
            r"(?m)^#{1,6}\s+(.+)$",
            lambda match: f"**{match.group(1).strip()}**",
            item["content"].strip(),
        )
        lines.extend(
            [
                f"## {item['name']}",
                f"- **knowledge_id:** `{item['knowledge_id']}`",
                f"- **category:** {item['category']}",
                f"- **difficulty:** {item['difficulty']}",
                f"- **tags:** {tags}",
                f"- **source:** [{source_title}]({item['source_url']})",
                f"- **license:** {item['license_note']}",
                f"- **ability_weights:** `{weights}`",
                "",
                content,
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def template_question_source(questions: list[dict[str, Any]], knowledge_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for question in questions:
        answer_key = question["answer_key"]
        purpose = answer_key["question_bank_uses"][0]
        grouped[(question["knowledge_id"], purpose)].append(question)

    selected_ids: set[str] = set()
    source_rows: list[dict[str, Any]] = []
    for knowledge_id in sorted(knowledge_ids):
        purpose_offsets: dict[str, int] = defaultdict(int)
        for purpose, slot_key, quiz_level in PURPOSE_SLOTS:
            candidates = sorted(grouped[(knowledge_id, purpose)], key=lambda item: item["question_id"])
            offset = purpose_offsets[purpose]
            if offset >= len(candidates):
                raise ValueError(
                    f"template-compatible question missing: {knowledge_id}/{purpose}/{slot_key}"
                )
            question = candidates[offset]
            purpose_offsets[purpose] += 1
            selected_ids.add(question["question_id"])
            answer_key = dict(question["answer_key"])
            # The template defines the slot's official level. Historical seed
            # questions may predate that inventory rule, so only the template
            # copy receives the normalized level; the bootstrap fixture remains
            # an exact runtime export.
            answer_key["quiz_level"] = quiz_level
            source_rows.append(
                {
                    "slot_key": slot_key,
                    "knowledge_id": knowledge_id,
                    "purpose": purpose,
                    "quiz_level": quiz_level,
                    "source_question_id": question["question_id"],
                    "question_type": question["question_type"],
                    "difficulty": question["difficulty"],
                    "stem": question["stem"],
                    "options": question["options"],
                    "answer_key": answer_key,
                }
            )
    if len(source_rows) != 450:
        raise ValueError(f"expected 450 template source rows, found {len(source_rows)}")
    supplemental = [
        question
        for question in questions
        if question["question_id"] not in selected_ids
        and question["answer_key"]["question_bank_uses"] == ["diagnosis"]
    ]
    if len(supplemental) != 15:
        raise ValueError(f"expected 15 supplemental diagnosis questions, found {len(supplemental)}")
    return source_rows, supplemental


def manual_demo_cases() -> dict[str, Any]:
    return {
        "schema_version": "manual-demo-cases-v1",
        "domain_code": "ai_app_dev",
        "privacy": "all learner identifiers are synthetic; no full answer text or generated resource is stored",
        "cases": [
            {
                "case_id": "DEMO-BEGINNER-INITIAL",
                "scenario": "初学者完成诊断后触发补救型初始生成",
                "trigger_type": "initial_generation",
                "profile_input": {"profile_type": "beginner", "ability_scores": {"theory": 32, "practice": 24, "problem_solving": 28, "knowledge_breadth": 30, "learning_speed": 45}, "weak_knowledge_ids": ["python_api_basics", "prompt_basic", "rag_pipeline_overview"]},
                "learning_goal": "掌握 AI 应用开发基础流程并完成一个可验证的 API 调用练习",
                "expected_assertions": {"terminal_status": "completed", "resource_types": ["lecture", "practice_guide", "graded_quiz"], "target_knowledge_ids_include": ["python_api_basics", "prompt_basic"], "review_status": "passed", "source_refs_present": True, "profile_update_decision": "no_change"},
            },
            {
                "case_id": "DEMO-INTERMEDIATE-FEEDBACK",
                "scenario": "进阶学习者报告资源存在可疑事实，触发定向复核",
                "trigger_type": "resource_feedback",
                "requires_completed_case": "DEMO-BEGINNER-INITIAL",
                "feedback_input": {"rating": 2, "quick_tags": ["有错误"], "message": "请核对资源中关于向量检索距离含义的表述，并给出来源依据。"},
                "expected_assertions": {"terminal_status": "completed", "review_action": "recheck_or_revision", "source_refs_present": True, "profile_update_decision": "no_change"},
            },
            {
                "case_id": "DEMO-ADVANCED-CHALLENGE",
                "scenario": "高阶学习者请求挑战任务，生成更高难度资源",
                "trigger_type": "resource_feedback",
                "profile_input": {"profile_type": "advanced", "ability_scores": {"theory": 86, "practice": 80, "problem_solving": 88, "knowledge_breadth": 82, "learning_speed": 78}, "weak_knowledge_ids": ["review_validation_agent"]},
                "feedback_input": {"rating": 5, "quick_tags": ["太简单"], "message": "当前内容已掌握，请提供多智能体审核仲裁的挑战任务。"},
                "expected_assertions": {"terminal_status": "completed", "resource_types": ["lecture", "practice_guide", "graded_quiz"], "target_knowledge_ids_include": ["review_validation_agent"], "review_status": "passed", "source_refs_present": True, "profile_update_decision": "challenge_or_update"},
            },
        ],
    }


def build() -> None:
    raw_items = read_json(SNAPSHOT_ROOT / "知识库快照" / "knowledge_items.json")
    raw_questions = read_json(SNAPSHOT_ROOT / "题库快照" / "diagnostic_questions.json")
    items = canonical_knowledge(raw_items)
    questions = canonical_questions(raw_questions)
    relations = relation_records(items)
    knowledge_ids = {item["knowledge_id"] for item in items}
    purpose_counts = Counter(question["answer_key"]["question_bank_uses"][0] for question in questions)
    relation_counts = Counter(relation["relation_type"] for relation in relations)
    if len(items) != 75 or len(questions) != 465:
        raise ValueError("runtime snapshots do not match the required 75/465 baseline")
    if relation_counts != Counter({"prerequisite": 92, "related": 14}):
        raise ValueError(f"unexpected relation counts: {dict(relation_counts)}")
    if purpose_counts != Counter({"diagnosis": 90, "graded_quiz": 225, "mastery_validation": 150}):
        raise ValueError(f"unexpected purpose counts: {dict(purpose_counts)}")

    domain = read_json(PROJECT_ROOT / "data" / "seed" / "ai_app_dev_domain.json")
    domain["mvp_targets"] = {**domain["mvp_targets"], "knowledge_items": 75, "diagnostic_questions": 465, "evaluation_cases": 50}
    write_json(FIXTURE_ROOT / "domain.json", domain)
    write_json(FIXTURE_ROOT / "knowledge_items.json", items)
    write_json(FIXTURE_ROOT / "relations.json", relations)
    write_json(FIXTURE_ROOT / "diagnostic_questions.json", questions)
    template_rows, supplemental = template_question_source(questions, knowledge_ids)
    write_json(FIXTURE_ROOT / "template_question_source.json", template_rows)
    write_json(FIXTURE_ROOT / "supplemental_diagnosis_questions.json", supplemental)
    write_json(FIXTURE_ROOT / "manual_demo_cases.json", manual_demo_cases())
    evaluation_cases = read_json(PROJECT_ROOT / "data" / "evaluation_cases" / "v4" / "p0_cases.json")
    write_json(FIXTURE_ROOT / "evaluation_cases_v4.json", evaluation_cases)
    write_json(FIXTURE_ROOT / "evaluation_manifest.json", read_json(PROJECT_ROOT / "data" / "evaluation_cases" / "manifest.json"))

    full_import_path = IMPORT_ROOT / "01-ai-app-dev-complete.md"
    fixture_import_path = FIXTURE_ROOT / "import_source" / full_import_path.name
    write_full_import_markdown(items, full_import_path)
    # Keep the runtime-verified copy inside data/ because the backend container
    # intentionally does not mount the competition deliverables directory.
    write_full_import_markdown(items, fixture_import_path)
    if sha256_file(full_import_path) != sha256_file(fixture_import_path):
        raise ValueError("fixture import source copy does not match deliverable")
    package_manifest_path = PROJECT_ROOT / "deliverables" / "knowledge-import-packages" / "manifest.json"
    package_manifest = read_json(package_manifest_path)
    if not isinstance(package_manifest, list):
        raise ValueError("knowledge import package manifest must be a JSON array")
    full_import_entry = {
        "domain_code": "ai_app_dev",
        "file": "ai_app_dev/01-ai-app-dev-complete.md",
        "knowledge_count": 75,
        "sha256": sha256_file(fixture_import_path),
        "mode": "empty_database_import_demo",
    }
    package_manifest = [
        item
        for item in package_manifest
        if not (isinstance(item, dict) and item.get("file") == full_import_entry["file"])
    ]
    write_json(package_manifest_path, [full_import_entry, *package_manifest])
    import_manifest = {
        "schema_version": "ai-app-dev-full-import-v1",
        "domain_code": "ai_app_dev",
        "mode": "empty_database_import_demo",
        "knowledge_count": 75,
        "file": full_import_path.name,
        "sha256": sha256_file(full_import_path),
        "source_fixture_version": FIXTURE_VERSION,
        "note": "Use this full import source or the bootstrap fixture, never both in one database.",
    }
    write_json(FIXTURE_ROOT / "import_source_manifest.json", import_manifest)

    file_names = (
        "domain.json",
        "knowledge_items.json",
        "relations.json",
        "diagnostic_questions.json",
        "template_question_source.json",
        "supplemental_diagnosis_questions.json",
        "manual_demo_cases.json",
        "evaluation_cases_v4.json",
        "evaluation_manifest.json",
        "import_source_manifest.json",
    )
    manifest = {
        "schema_version": "submission-fixture-manifest-v1",
        "fixture_version": FIXTURE_VERSION,
        "domain_code": "ai_app_dev",
        "source_snapshots": {
            "knowledge_items": "deliverables/competition-initial-review/07_测试数据与案例/知识库快照/knowledge_items.json",
            "diagnostic_questions": "deliverables/competition-initial-review/07_测试数据与案例/题库快照/diagnostic_questions.json",
        },
        "counts": {
            "knowledge_items": 75,
            "prerequisite_relations": 92,
            "related_relations": 14,
            "active_questions": 465,
            "question_purposes": dict(sorted(purpose_counts.items())),
            "template_compatible_questions": 450,
            "supplemental_diagnosis_questions": 15,
            "evaluation_cases": 50,
            "manual_demo_cases": 3,
        },
        "files": {name: {"sha256": sha256_file(FIXTURE_ROOT / name)} for name in file_names},
        "import_source": {
            "path": fixture_import_path.relative_to(FIXTURE_ROOT).as_posix(),
            "sha256": sha256_file(fixture_import_path),
            "deliverable_path": full_import_path.relative_to(PROJECT_ROOT).as_posix(),
        },
        "reproduction_modes": {
            "bootstrap": "load the fixture into an empty database",
            "import_demo": "upload the Markdown, then download and fill a current question template",
        },
    }
    write_json(FIXTURE_ROOT / "manifest.json", manifest)
    print(json.dumps({"fixture_root": str(FIXTURE_ROOT), "manifest": manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
