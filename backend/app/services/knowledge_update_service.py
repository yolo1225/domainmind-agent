from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import (
    GenerationTask,
    KnowledgeItem,
    KnowledgeRelation,
    LearningPath,
    LearningResource,
)


def _collect_strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        result: set[str] = set()
        for item in value.values():
            result.update(_collect_strings(item))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_collect_strings(item))
        return result
    return set()


def related_knowledge_ids(db: Session, item: KnowledgeItem) -> set[str]:
    relations = list(
        db.scalars(
            select(KnowledgeRelation).where(
                or_(
                    KnowledgeRelation.source_item_id == item.id,
                    KnowledgeRelation.target_item_id == item.id,
                )
            )
        )
    )
    internal_ids = {item.id}
    for relation in relations:
        internal_ids.add(relation.source_item_id)
        internal_ids.add(relation.target_item_id)
    return set(
        db.scalars(select(KnowledgeItem.public_id).where(KnowledgeItem.id.in_(internal_ids)))
    )


def replace_item_relations(
    db: Session,
    *,
    item: KnowledgeItem,
    relation_type: str,
    source_public_ids: Iterable[str],
) -> None:
    requested = list(dict.fromkeys(source_public_ids))
    if item.public_id in requested:
        raise ValueError("knowledge relation cannot reference itself")
    sources = list(
        db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == item.domain_code,
                KnowledgeItem.public_id.in_(requested),
            )
        )
    ) if requested else []
    found = {source.public_id for source in sources}
    missing = sorted(set(requested) - found)
    if missing:
        raise ValueError(f"unknown knowledge relation targets: {', '.join(missing)}")

    db.execute(
        delete(KnowledgeRelation).where(
            KnowledgeRelation.target_item_id == item.id,
            KnowledgeRelation.relation_type == relation_type,
        )
    )
    for source in sources:
        db.add(
            KnowledgeRelation(
                source_item_id=source.id,
                target_item_id=item.id,
                relation_type=relation_type,
            )
        )
    db.flush()


def mark_affected_content(
    db: Session,
    *,
    domain_code: str,
    affected_knowledge_ids: set[str],
    reason: str,
) -> dict[str, int]:
    path_count = 0
    paths = list(db.scalars(select(LearningPath).where(LearningPath.domain_code == domain_code)))
    for path in paths:
        if not (_collect_strings(path.path_json or {}) & affected_knowledge_ids):
            continue
        path.needs_refresh = True
        path.path_json = {
            **(path.path_json or {}),
            "knowledge_update_reason": reason,
            "affected_knowledge_ids": sorted(affected_knowledge_ids),
        }
        path_count += 1

    resource_count = 0
    resources = list(
        db.scalars(
            select(LearningResource)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(GenerationTask.domain_code == domain_code, LearningResource.is_current.is_(True))
        )
    )
    for resource in resources:
        source_ids = {
            str(source.get("knowledge_id"))
            for source in (resource.sources_json or [])
            if isinstance(source, dict) and source.get("knowledge_id")
        }
        if not (source_ids & affected_knowledge_ids):
            continue
        resource.review_status = "review_stale"
        resource_count += 1

    return {"learning_paths": path_count, "resources": resource_count}
