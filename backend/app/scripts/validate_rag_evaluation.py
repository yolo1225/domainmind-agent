from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agents.contracts import RetrieveKnowledgeInput
from app.scripts.validate_rag_seed import load_knowledge_items, source_data_version


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "rag_evaluation"
DEFAULT_KNOWLEDGE_PATH = PROJECT_ROOT / "data" / "seed" / "knowledge_items.json"
EXPECTED_COUNTS = {"development": 30, "acceptance": 20}
MINIMUM_HIDDEN_CASES = {"development": 12, "acceptance": 8}
SCHEMA_VERSION = "rag-evaluation-1.0"
MANIFEST_SCHEMA_VERSION = "rag-evaluation-manifest-1.0"
VALID_ROUTES = {"priority", "prerequisite", "semantic", "related", "dependent"}
VALID_INPUT_ROLES = {"priority", "prerequisite", "none"}
EXPECTED_PURPOSES = {
    "remedial_explanation",
    "consolidation_practice",
    "challenge_task",
    "source_verification",
}
EXPECTED_STRATEGIES = {"remedial", "consolidation", "challenge"}


class RagEvaluationValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_cases_sha256(cases: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        sorted(cases, key=lambda case: str(case.get("case_id", ""))),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def load_evaluation_data(
    data_dir: Path = DEFAULT_DATA_DIR,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    datasets: dict[str, list[dict[str, Any]]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for split in EXPECTED_COUNTS:
        payload = _load_json(data_dir / f"{split}_cases.json")
        if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
            raise RagEvaluationValidationError([f"{split}: payload must contain a cases array"])
        datasets[split] = payload["cases"]
        metadata[split] = {key: value for key, value in payload.items() if key != "cases"}
    return datasets, {"datasets": metadata, "manifest": _load_json(data_dir / "manifest.json")}


def materialize_retrieve_input(case: dict[str, Any], domain_code: str) -> RetrieveKnowledgeInput:
    case_id = str(case["case_id"])
    profile_type = str(case["profile_type"])
    scores = {
        "beginner": (35, 30, 35, 30, 45),
        "intermediate": (65, 60, 65, 60, 65),
        "advanced": (85, 85, 85, 85, 80),
    }[profile_type]
    resource_types = case["retrieval_plan"]["resource_types"]
    return RetrieveKnowledgeInput.model_validate(
        {
            "task_id": case_id,
            "context": {
                "task_id": case_id,
                "session_id": f"session-{case_id.lower()}",
                "trigger_type": "initial_generation",
                "execution_mode": "auto",
                "learner_id": f"gold-{profile_type}",
                "profile_id": f"gold-profile-{profile_type}",
                "domain_code": domain_code,
                "resource_types": resource_types,
                "learning_goal": case["learning_goal"],
            },
            "profile": {
                "profile_id": f"gold-profile-{profile_type}",
                "profile_version": 1,
                "profile_type": profile_type,
                "ability_scores": dict(
                    zip(
                        (
                            "theory",
                            "practice",
                            "problem_solving",
                            "knowledge_breadth",
                            "learning_speed",
                        ),
                        scores,
                        strict=True,
                    )
                ),
                "weak_knowledge": [],
                "blind_spot_ids": case["retrieval_plan"]["priority_knowledge_ids"],
            },
            "retrieval_plan": case["retrieval_plan"],
            "purpose": case["purpose"],
        }
    )


def _relation_is_valid(
    label: dict[str, Any], gold_ids: set[str], knowledge_by_id: dict[str, dict[str, Any]]
) -> bool:
    knowledge_id = str(label.get("knowledge_id", ""))
    route = label.get("expected_route")
    if route in {"priority", "semantic"}:
        return True
    if route == "prerequisite":
        return any(
            knowledge_id in knowledge_by_id[other_id].get("prerequisites", [])
            for other_id in gold_ids - {knowledge_id}
        )
    if route == "dependent":
        return bool(set(knowledge_by_id[knowledge_id].get("prerequisites", [])) & gold_ids)
    if route == "related":
        return any(
            knowledge_id in knowledge_by_id[other_id].get("related", [])
            or other_id in knowledge_by_id[knowledge_id].get("related", [])
            for other_id in gold_ids - {knowledge_id}
        )
    return False


def validate_rag_evaluation(
    data_dir: Path = DEFAULT_DATA_DIR,
    knowledge_path: Path = DEFAULT_KNOWLEDGE_PATH,
) -> dict[str, Any]:
    datasets, metadata = load_evaluation_data(data_dir)
    knowledge_items = load_knowledge_items(knowledge_path)
    knowledge_by_id = {str(item["knowledge_id"]): item for item in knowledge_items}
    knowledge_ids = set(knowledge_by_id)
    actual_source_version = source_data_version(knowledge_items)
    errors: list[str] = []
    all_case_ids: list[str] = []
    all_gold_ids: set[str] = set()
    split_results: dict[str, Any] = {}

    for split, cases in datasets.items():
        split_meta = metadata["datasets"][split]
        if split_meta.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"{split}: unsupported schema_version")
        if split_meta.get("split") != split:
            errors.append(f"{split}: split metadata mismatch")
        if split_meta.get("domain_code") != "ai_app_dev":
            errors.append(f"{split}: domain_code must be ai_app_dev")
        if split_meta.get("source_data_version") != actual_source_version:
            errors.append(f"{split}: source_data_version does not match knowledge seed")
        if len(cases) != EXPECTED_COUNTS[split]:
            errors.append(f"{split}: expected {EXPECTED_COUNTS[split]} cases, found {len(cases)}")

        purposes: set[str] = set()
        strategies: set[str] = set()
        difficulties: set[int] = set()
        hidden_case_count = 0
        split_gold_ids: set[str] = set()

        for case in cases:
            case_id = str(case.get("case_id", "")).strip()
            all_case_ids.append(case_id)
            prefix = "RAG-DEV-" if split == "development" else "RAG-ACC-"
            if not case_id.startswith(prefix):
                errors.append(f"{case_id or '<missing>'}: invalid case ID prefix")
            for field in ("query", "learning_goal"):
                if not isinstance(case.get(field), str) or not case[field].strip():
                    errors.append(f"{case_id}: {field} must be non-empty")

            plan = case.get("retrieval_plan")
            if not isinstance(plan, dict):
                errors.append(f"{case_id}: retrieval_plan must be an object")
                continue
            priority_ids = plan.get("priority_knowledge_ids", [])
            prerequisite_ids = plan.get("prerequisite_knowledge_ids", [])
            if set(priority_ids) & set(prerequisite_ids):
                errors.append(f"{case_id}: priority and prerequisite inputs must be disjoint")
            if plan.get("n_results") != 12:
                errors.append(f"{case_id}: n_results must equal 12")

            labels = case.get("gold_knowledge")
            if not isinstance(labels, list) or not labels:
                errors.append(f"{case_id}: gold_knowledge must be non-empty")
                continue
            gold_ids = {str(label.get("knowledge_id", "")) for label in labels}
            if len(gold_ids) != len(labels):
                errors.append(f"{case_id}: duplicate gold knowledge IDs")
            invalid_ids = sorted(gold_ids - knowledge_ids)
            if invalid_ids:
                errors.append(f"{case_id}: invalid knowledge IDs: {', '.join(invalid_ids)}")
                continue
            split_gold_ids.update(gold_ids)
            all_gold_ids.update(gold_ids)

            hidden = False
            for label in labels:
                knowledge_id = str(label.get("knowledge_id", ""))
                route = label.get("expected_route")
                role = label.get("input_role")
                if route not in VALID_ROUTES:
                    errors.append(f"{case_id}:{knowledge_id}: invalid expected_route")
                if role not in VALID_INPUT_ROLES:
                    errors.append(f"{case_id}:{knowledge_id}: invalid input_role")
                if role == "priority" and knowledge_id not in priority_ids:
                    errors.append(f"{case_id}:{knowledge_id}: priority label missing from input")
                if role == "prerequisite" and knowledge_id not in prerequisite_ids:
                    errors.append(f"{case_id}:{knowledge_id}: prerequisite label missing from input")
                if role == "none":
                    hidden = True
                    if knowledge_id in priority_ids or knowledge_id in prerequisite_ids:
                        errors.append(f"{case_id}:{knowledge_id}: hidden gold leaked into input")
                if not isinstance(label.get("reason"), str) or not label["reason"].strip():
                    errors.append(f"{case_id}:{knowledge_id}: annotation reason is required")
                if knowledge_id in knowledge_by_id and not _relation_is_valid(
                    label, gold_ids, knowledge_by_id
                ):
                    errors.append(f"{case_id}:{knowledge_id}: route is not supported by relations")

            role_priority = {x["knowledge_id"] for x in labels if x.get("input_role") == "priority"}
            role_prerequisite = {
                x["knowledge_id"] for x in labels if x.get("input_role") == "prerequisite"
            }
            if role_priority != set(priority_ids) or role_prerequisite != set(prerequisite_ids):
                errors.append(f"{case_id}: explicit inputs and gold input_role labels differ")
            if hidden:
                hidden_case_count += 1

            purposes.add(str(case.get("purpose", "")))
            strategies.add(str(plan.get("strategy", "")))
            difficulty = plan.get("target_difficulty")
            if isinstance(difficulty, int):
                difficulties.add(difficulty)
            try:
                materialize_retrieve_input(case, str(split_meta.get("domain_code")))
            except (KeyError, TypeError, ValidationError, ValueError) as exc:
                errors.append(f"{case_id}: cannot materialize RetrieveKnowledgeInput: {exc}")

        if hidden_case_count < MINIMUM_HIDDEN_CASES[split]:
            errors.append(
                f"{split}: expected at least {MINIMUM_HIDDEN_CASES[split]} hidden-answer cases"
            )
        if purposes != EXPECTED_PURPOSES:
            errors.append(f"{split}: all four retrieval purposes are required")
        if strategies != EXPECTED_STRATEGIES:
            errors.append(f"{split}: all three strategies are required")
        if difficulties != {1, 2, 3, 4, 5}:
            errors.append(f"{split}: target difficulties 1 through 5 are required")
        split_results[split] = {
            "case_count": len(cases),
            "gold_knowledge_count": len(split_gold_ids),
            "hidden_answer_cases": hidden_case_count,
            "content_sha256": canonical_cases_sha256(cases),
        }

    duplicates = sorted(case_id for case_id, count in Counter(all_case_ids).items() if count > 1)
    if not all(all_case_ids) or duplicates:
        errors.append(f"case IDs must be non-empty and unique: {', '.join(duplicates)}")
    missing_gold_ids = sorted(knowledge_ids - all_gold_ids)
    if missing_gold_ids:
        errors.append(f"knowledge IDs missing from gold coverage: {', '.join(missing_gold_ids)}")

    manifest = metadata["manifest"]
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("manifest: unsupported schema_version")
    if manifest.get("source_data_version") != actual_source_version:
        errors.append("manifest: source_data_version does not match knowledge seed")
    for split, expected in EXPECTED_COUNTS.items():
        if manifest.get(f"{split}_case_count") != expected:
            errors.append(f"manifest: {split}_case_count mismatch")
    acceptance_hash = split_results["acceptance"]["content_sha256"]
    if manifest.get("acceptance_cases_sha256") != acceptance_hash:
        errors.append("manifest: frozen acceptance content hash mismatch")

    if errors:
        raise RagEvaluationValidationError(errors)
    return {
        "status": "passed",
        "schema_version": SCHEMA_VERSION,
        "domain_code": "ai_app_dev",
        "source_data_version": actual_source_version,
        "total_case_count": sum(len(cases) for cases in datasets.values()),
        "covered_knowledge_count": len(all_gold_ids),
        "splits": split_results,
        "acceptance_cases_sha256": acceptance_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the dedicated RAG gold dataset.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--knowledge-path", type=Path, default=DEFAULT_KNOWLEDGE_PATH)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()
    try:
        result = validate_rag_evaluation(args.data_dir, args.knowledge_path)
    except (OSError, json.JSONDecodeError, RagEvaluationValidationError) as exc:
        errors = exc.errors if isinstance(exc, RagEvaluationValidationError) else [str(exc)]
        if args.json:
            print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=2))
        else:
            print(f"RAG evaluation validation failed: {'; '.join(errors)}")
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "RAG evaluation validation passed: "
            f"{result['total_case_count']} cases, "
            f"{result['covered_knowledge_count']} knowledge IDs, "
            f"acceptance_hash={result['acceptance_cases_sha256']}."
        )


if __name__ == "__main__":
    main()
