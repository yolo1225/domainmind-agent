from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_DOMAIN_CODE = "ai_app_dev"
DEFAULT_EXPECTED_ITEMS = 50
DEFAULT_EXPECTED_PREREQUISITES = 67
DEFAULT_EXPECTED_RELATED = 14
DEFAULT_EXPECTED_QUESTIONS = 60
DEFAULT_MINIMUM_CONTENT_CHARACTERS = 120
DEFAULT_EXPECTED_LONG_ITEMS = 3
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KNOWLEDGE_PATH = PROJECT_ROOT / "data" / "seed" / "knowledge_items.json"
DEFAULT_QUESTIONS_PATH = PROJECT_ROOT / "data" / "seed" / "diagnostic_questions.json"
RETIRED_KNOWLEDGE_IDS = {
    "demo_script_design",
    "diagnostic_question_design",
    "feedback_loop_update",
    "learner_profile_model",
    "learning_path_generation",
    "profile_analysis_agent",
    "review_dual_model",
    "tutoring_feedback_agent",
}
INTERNAL_SOURCE_MARKERS = (
    "project-internal",
    "当前迭代计划",
    "项目需求文档",
    "项目设计文档",
)
INTERNAL_CONTENT_MARKERS = (
    "agent_runs",
    "generation_tasks",
    "manual_review_required",
    "primary_review_model",
    "secondary_review_model",
    "test_script",
    "冻结契约",
    "本项目",
    "竞赛演示",
)


class SeedValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def load_knowledge_items(path: Path = DEFAULT_KNOWLEDGE_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SeedValidationError(["knowledge seed must be a JSON array"])
    if not all(isinstance(item, dict) for item in payload):
        raise SeedValidationError(["every knowledge seed entry must be a JSON object"])
    return payload


def load_diagnostic_questions(
    path: Path = DEFAULT_QUESTIONS_PATH,
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SeedValidationError(["diagnostic question seed must be a JSON array"])
    if not all(isinstance(item, dict) for item in payload):
        raise SeedValidationError(
            ["every diagnostic question seed entry must be a JSON object"]
        )
    return payload


def source_data_version(items: list[dict[str, Any]]) -> str:
    canonical_items = sorted(items, key=lambda item: str(item.get("knowledge_id", "")))
    canonical = json.dumps(
        canonical_items,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_knowledge_items(
    items: list[dict[str, Any]],
    *,
    domain_code: str = DEFAULT_DOMAIN_CODE,
    expected_items: int = DEFAULT_EXPECTED_ITEMS,
    expected_prerequisites: int = DEFAULT_EXPECTED_PREREQUISITES,
    expected_related: int = DEFAULT_EXPECTED_RELATED,
    minimum_content_characters: int = DEFAULT_MINIMUM_CONTENT_CHARACTERS,
    expected_long_items: int = DEFAULT_EXPECTED_LONG_ITEMS,
) -> dict[str, Any]:
    errors: list[str] = []
    ids = [str(item.get("knowledge_id", "")).strip() for item in items]
    id_counts = Counter(ids)
    duplicate_ids = sorted(item_id for item_id, count in id_counts.items() if item_id and count > 1)
    if duplicate_ids:
        errors.append(f"duplicate knowledge_id values: {', '.join(duplicate_ids)}")
    if any(not item_id for item_id in ids):
        errors.append("knowledge_id must be non-empty for every item")
    if len(items) != expected_items:
        errors.append(f"expected {expected_items} items, found {len(items)}")

    known_ids = set(ids)
    retired_ids = sorted(known_ids & RETIRED_KNOWLEDGE_IDS)
    if retired_ids:
        errors.append(f"retired knowledge IDs are not allowed: {', '.join(retired_ids)}")
    prerequisite_count = 0
    related_count = 0
    invalid_relations: list[str] = []
    self_relations: list[str] = []
    contents: list[str] = []
    source_url_count = 0

    for item in items:
        item_id = str(item.get("knowledge_id", "")).strip() or "<missing-id>"
        if item.get("domain_code") != domain_code:
            errors.append(f"{item_id}: domain_code must be {domain_code}")

        for field in ("name", "category", "content", "source_title", "license_note"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{item_id}: {field} must be a non-empty string")

        content = item.get("content")
        if isinstance(content, str):
            normalized_content = content.strip()
            contents.append(normalized_content)
            if len(normalized_content) < minimum_content_characters:
                errors.append(
                    f"{item_id}: content must contain at least "
                    f"{minimum_content_characters} characters"
                )
            if any(marker in normalized_content for marker in INTERNAL_CONTENT_MARKERS):
                errors.append(f"{item_id}: project-specific content is not allowed")

        difficulty = item.get("difficulty")
        if not isinstance(difficulty, int) or isinstance(difficulty, bool) or not 1 <= difficulty <= 5:
            errors.append(f"{item_id}: difficulty must be an integer from 1 to 5")

        tags = item.get("tags")
        if not isinstance(tags, list) or not tags or any(not isinstance(tag, str) or not tag for tag in tags):
            errors.append(f"{item_id}: tags must be a non-empty list of strings")

        source_url = item.get("source_url")
        if not isinstance(source_url, str) or not _is_http_url(source_url):
            errors.append(f"{item_id}: source_url must be an absolute HTTP(S) URL")
        else:
            source_url_count += 1

        source_fields = " ".join(
            str(item.get(field, "")) for field in ("source_title", "license_note")
        ).lower()
        if any(marker.lower() in source_fields for marker in INTERNAL_SOURCE_MARKERS):
            errors.append(f"{item_id}: project-internal sources are not allowed")

        license_note = item.get("license_note")
        if isinstance(license_note, str) and "official" in license_note and not source_url:
            errors.append(f"{item_id}: official documentation reference requires source_url")

        for relation_type in ("prerequisites", "related"):
            relations = item.get(relation_type, [])
            if not isinstance(relations, list):
                errors.append(f"{item_id}: {relation_type} must be a list")
                continue
            valid_relation_ids = [
                relation_id
                for relation_id in relations
                if isinstance(relation_id, str) and relation_id.strip()
            ]
            if len(valid_relation_ids) != len(relations):
                errors.append(f"{item_id}: {relation_type} must contain non-empty string IDs")
            if len(valid_relation_ids) != len(set(valid_relation_ids)):
                errors.append(f"{item_id}: {relation_type} contains duplicate IDs")
            if relation_type == "prerequisites":
                prerequisite_count += len(relations)
            else:
                related_count += len(relations)
            for related_id in valid_relation_ids:
                if related_id == item_id:
                    self_relations.append(f"{item_id}:{relation_type}")
                if related_id not in known_ids:
                    invalid_relations.append(f"{item_id}:{relation_type}:{related_id}")

    if prerequisite_count != expected_prerequisites:
        errors.append(
            f"expected {expected_prerequisites} prerequisite relations, found {prerequisite_count}"
        )
    if related_count != expected_related:
        errors.append(f"expected {expected_related} related relations, found {related_count}")
    if invalid_relations:
        errors.append(f"invalid relation IDs: {', '.join(sorted(invalid_relations))}")
    if self_relations:
        errors.append(f"self relations: {', '.join(sorted(self_relations))}")

    long_item_count = sum(len(content) > 800 for content in contents)
    if long_item_count < expected_long_items:
        errors.append(
            f"expected at least {expected_long_items} items over 800 characters, "
            f"found {long_item_count}"
        )

    if errors:
        raise SeedValidationError(errors)

    content_lengths = [len(content) for content in contents]
    return {
        "status": "passed",
        "domain_code": domain_code,
        "source_data_version": source_data_version(items),
        "counts": {
            "knowledge_items": len(items),
            "unique_knowledge_ids": len(known_ids),
            "prerequisite_relations": prerequisite_count,
            "related_relations": related_count,
            "invalid_relations": len(invalid_relations),
            "self_relations": len(self_relations),
        },
        "content": {
            "minimum_characters": min(content_lengths, default=0),
            "average_characters": round(sum(content_lengths) / len(content_lengths), 1),
            "maximum_characters": max(content_lengths, default=0),
            "over_800_characters": long_item_count,
        },
        "sources": {
            "complete_required_fields": len(items),
            "with_source_url": source_url_count,
            "required_field_completeness": 1.0,
        },
    }


def validate_diagnostic_questions(
    questions: list[dict[str, Any]],
    *,
    knowledge_ids: set[str],
    expected_questions: int = DEFAULT_EXPECTED_QUESTIONS,
) -> dict[str, Any]:
    errors: list[str] = []
    question_ids = [str(question.get("question_id", "")).strip() for question in questions]
    question_id_counts = Counter(question_ids)
    duplicates = sorted(
        question_id
        for question_id, count in question_id_counts.items()
        if question_id and count > 1
    )
    if duplicates:
        errors.append(f"duplicate question_id values: {', '.join(duplicates)}")
    if any(not question_id for question_id in question_ids):
        errors.append("question_id must be non-empty for every diagnostic question")
    if len(questions) != expected_questions:
        errors.append(f"expected {expected_questions} questions, found {len(questions)}")

    invalid_knowledge_refs: list[str] = []
    type_counts: Counter[str] = Counter()
    for question in questions:
        question_id = str(question.get("question_id", "")).strip() or "<missing-id>"
        knowledge_id = str(question.get("knowledge_id", "")).strip()
        if not knowledge_id or knowledge_id not in knowledge_ids:
            invalid_knowledge_refs.append(f"{question_id}:{knowledge_id or '<missing-id>'}")

        stem = question.get("stem")
        if not isinstance(stem, str) or not stem.strip():
            errors.append(f"{question_id}: stem must be a non-empty string")

        difficulty = question.get("difficulty")
        if (
            not isinstance(difficulty, int)
            or isinstance(difficulty, bool)
            or not 1 <= difficulty <= 5
        ):
            errors.append(f"{question_id}: difficulty must be an integer from 1 to 5")

        question_type = question.get("question_type")
        if question_type not in {"single_choice", "short_answer"}:
            errors.append(f"{question_id}: unsupported question_type {question_type!r}")
            continue
        type_counts[question_type] += 1

        answer_key = question.get("answer_key")
        if not isinstance(answer_key, dict):
            errors.append(f"{question_id}: answer_key must be an object")
            continue

        if question_type == "single_choice":
            options = question.get("options")
            if (
                not isinstance(options, list)
                or len(options) < 2
                or any(not isinstance(option, str) or not option.strip() for option in options)
                or len(options) != len(set(options))
            ):
                errors.append(
                    f"{question_id}: single_choice options must be unique non-empty strings"
                )
                continue
            correct_option = answer_key.get("correct_option")
            if (
                not isinstance(correct_option, int)
                or isinstance(correct_option, bool)
                or not 0 <= correct_option < len(options)
            ):
                errors.append(f"{question_id}: correct_option must reference an option")
        else:
            rubric = answer_key.get("rubric")
            if (
                not isinstance(rubric, list)
                or not rubric
                or any(not isinstance(item, str) or not item.strip() for item in rubric)
            ):
                errors.append(f"{question_id}: short_answer rubric must be non-empty")

    if invalid_knowledge_refs:
        errors.append(
            "invalid diagnostic knowledge references: "
            + ", ".join(sorted(invalid_knowledge_refs))
        )
    if errors:
        raise SeedValidationError(errors)

    return {
        "total": len(questions),
        "unique_question_ids": len(set(question_ids)),
        "single_choice": type_counts["single_choice"],
        "short_answer": type_counts["short_answer"],
        "invalid_knowledge_references": len(invalid_knowledge_refs),
    }


def validate_seed(
    path: Path = DEFAULT_KNOWLEDGE_PATH,
    questions_path: Path = DEFAULT_QUESTIONS_PATH,
) -> dict[str, Any]:
    items = load_knowledge_items(path)
    result = validate_knowledge_items(items)
    result["diagnostic_questions"] = validate_diagnostic_questions(
        load_diagnostic_questions(questions_path),
        knowledge_ids={str(item["knowledge_id"]) for item in items},
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the ai_app_dev RAG knowledge seed.")
    parser.add_argument("--path", type=Path, default=DEFAULT_KNOWLEDGE_PATH)
    parser.add_argument("--questions-path", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()

    try:
        result = validate_seed(args.path, args.questions_path)
    except (OSError, json.JSONDecodeError, SeedValidationError) as exc:
        if args.json:
            errors = exc.errors if isinstance(exc, SeedValidationError) else [str(exc)]
            print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=2))
        else:
            print(f"RAG seed validation failed: {exc}")
        raise SystemExit(1) from exc

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        counts = result["counts"]
        print(
            "RAG seed validation passed: "
            f"{counts['knowledge_items']} items, "
            f"{result['diagnostic_questions']['total']} questions, "
            f"{counts['prerequisite_relations']} prerequisite relations, "
            f"{counts['related_relations']} related relations, "
            f"version={result['source_data_version']}."
        )


if __name__ == "__main__":
    main()
