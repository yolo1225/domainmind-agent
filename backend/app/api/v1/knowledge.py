from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.agents.domain_evidence_policy import classify_evidence_capabilities
from app.models import DiagnosticQuestion, KnowledgeItem, KnowledgeRelation
from app.rag.readiness import candidate_rag_status
from app.schemas.common import ApiResponse, ok
from app.services import candidate_index_job
from app.services.domain_api_service import default_ability_weights, mark_domain_preparing
from app.services.question_bank_service import question_bank_coverage
from app.services.knowledge_update_service import (
    mark_affected_questions_stale,
    mark_affected_content,
    related_knowledge_ids,
    replace_item_relations,
)

router = APIRouter()


class QuestionDisableRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=255)


def _serialize_question(question: DiagnosticQuestion, item: KnowledgeItem) -> dict[str, Any]:
    answer_key = dict(question.answer_key_json or {})
    return {
        "question_id": question.public_id,
        "domain_code": question.domain_code,
        "knowledge_id": item.public_id,
        "knowledge_name": item.name,
        "related_knowledge_ids": list(question.related_knowledge_ids_json or []),
        "question_slot": answer_key.get("question_slot"),
        "question_bank_uses": list(answer_key.get("question_bank_uses") or []),
        "reserve_role": answer_key.get("reserve_role"),
        "assessment_focus": answer_key.get("assessment_focus"),
        "quiz_level": answer_key.get("quiz_level"),
        "question_type": question.question_type,
        "stem": question.stem,
        "options": list(question.options_json or []),
        "answer": answer_key.get("correct_option", answer_key.get("answer")),
        "explanation": answer_key.get("explanation"),
        "difficulty": question.difficulty,
        "status": question.status,
        "disabled_at": question.disabled_at,
        "disabled_reason": question.disabled_reason,
    }


@router.get("/questions", response_model=ApiResponse)
def list_question_bank(
    domain_code: str = Query(...),
    knowledge_id: str | None = Query(default=None),
    question_type: str | None = Query(default=None),
    quiz_level: str | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(active|staged|stale|disabled)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ApiResponse:
    filters = [DiagnosticQuestion.domain_code == domain_code]
    if knowledge_id:
        filters.append(KnowledgeItem.public_id == knowledge_id)
    if question_type:
        filters.append(DiagnosticQuestion.question_type == question_type)
    if status:
        filters.append(DiagnosticQuestion.status == status)
    rows = list(
        db.execute(
            select(DiagnosticQuestion, KnowledgeItem)
            .join(KnowledgeItem, DiagnosticQuestion.knowledge_item_id == KnowledgeItem.id)
            .where(*filters)
            .order_by(KnowledgeItem.public_id, DiagnosticQuestion.id)
        )
    )
    if quiz_level:
        rows = [
            row for row in rows
            if (row[0].answer_key_json or {}).get("quiz_level") == quiz_level
        ]
    total = len(rows)
    rows = rows[offset : offset + limit]
    return ok({
        "domain_code": domain_code,
        "items": [_serialize_question(question, item) for question, item in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "coverage": question_bank_coverage(db, domain_code=domain_code),
    })


@router.post("/questions/{question_id}/disable", response_model=ApiResponse)
def disable_question(
    question_id: str,
    payload: QuestionDisableRequest,
    db: Session = Depends(get_db),
) -> ApiResponse:
    row = db.execute(
        select(DiagnosticQuestion, KnowledgeItem)
        .join(KnowledgeItem, DiagnosticQuestion.knowledge_item_id == KnowledgeItem.id)
        .where(DiagnosticQuestion.public_id == question_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Question not found")
    question, item = row
    if question.status != "disabled":
        question.status = "disabled"
        question.disabled_at = datetime.now(UTC).replace(tzinfo=None)
        question.disabled_reason = payload.reason.strip()
        mark_domain_preparing(db, question.domain_code)
        db.commit()
        db.refresh(question)
    coverage = question_bank_coverage(
        db, domain_code=question.domain_code, knowledge_ids=[item.public_id]
    )
    return ok({
        "question": _serialize_question(question, item),
        "coverage": coverage,
        "replenishment": {
            "required": item.public_id in coverage["missing_knowledge_ids"],
            "knowledge_id": item.public_id,
            "status": "question_template_required",
            "next_action": "download_question_template",
        },
    })


@router.get("/relations", response_model=ApiResponse)
def list_knowledge_relations(
    domain_code: str = Query(...),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ApiResponse:
    items = list(
        db.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.status == "published",
            )
        )
    )
    item_by_id = {item.id: item for item in items}
    if not item_by_id:
        return ok([])
    relations = list(
        db.scalars(
            select(KnowledgeRelation)
            .where(KnowledgeRelation.source_item_id.in_(item_by_id))
            .order_by(KnowledgeRelation.id)
            .limit(limit)
        )
    )
    return ok(
        [
            {
                "source_id": item_by_id[relation.source_item_id].public_id,
                "source_name": item_by_id[relation.source_item_id].name,
                "target_id": item_by_id[relation.target_item_id].public_id,
                "target_name": item_by_id[relation.target_item_id].name,
                "relation_type": relation.relation_type,
            }
            for relation in relations
            if relation.source_item_id in item_by_id and relation.target_item_id in item_by_id
        ]
    )


class KnowledgeItemCreate(BaseModel):
    domain_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(default="未分类", min_length=1, max_length=64)
    difficulty: int = Field(default=2, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    content: str = Field(min_length=10)
    source_title: str = Field(default="教师手动导入", min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=512)
    license_note: str = Field(default="manual-import", max_length=255)
    prerequisites: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)


class KnowledgeItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None
    content: str | None = Field(default=None, min_length=10)
    source_title: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=512)
    license_note: str | None = Field(default=None, max_length=255)
    prerequisites: list[str] | None = None
    related: list[str] | None = None


def serialize_knowledge_item(item: KnowledgeItem) -> dict[str, Any]:
    return {
        "knowledge_id": item.public_id,
        "domain_code": item.domain_code,
        "name": item.name,
        "category": item.category,
        "difficulty": item.difficulty,
        "tags": item.tags_json or [],
        "evidence_capabilities": item.evidence_capabilities_json or [],
        "content": item.content_md,
        "source_title": item.source_title,
        "source_url": item.source_url,
        "license_note": item.license_note,
        "needs_reembedding": item.needs_reembedding,
        "ability_weights": item.ability_weights_json or {},
        "source_locator": item.source_locator_json or {},
        "status": item.status,
    }


@router.get("/items", response_model=ApiResponse)
def list_knowledge_items(
    domain_code: str = Query(...),
    category: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ApiResponse:
    filters = [
        KnowledgeItem.domain_code == domain_code,
        KnowledgeItem.status == "published",
    ]
    if category:
        filters.append(KnowledgeItem.category == category)

    total = db.scalar(select(func.count()).select_from(KnowledgeItem).where(*filters)) or 0
    items = list(
        db.scalars(
            select(KnowledgeItem)
            .where(*filters)
            .order_by(KnowledgeItem.category, KnowledgeItem.public_id)
            .offset(offset)
            .limit(limit)
        )
    )
    return ok(
        {
            "domain_code": domain_code,
            "items": [serialize_knowledge_item(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "mvp_target": 50,
        }
    )


@router.post("/items", response_model=ApiResponse)
def create_knowledge_item(
    payload: KnowledgeItemCreate,
    db: Session = Depends(get_db),
) -> ApiResponse:
    duplicate = db.scalar(
        select(KnowledgeItem).where(
            KnowledgeItem.domain_code == payload.domain_code,
            KnowledgeItem.name == payload.name,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409, detail=f"Knowledge item already exists: {payload.name}"
        )

    item = KnowledgeItem(
        public_id=f"ki_{uuid4().hex[:12]}",
        domain_code=payload.domain_code,
        name=payload.name.strip(),
        category=payload.category.strip(),
        difficulty=payload.difficulty,
        tags_json=[tag.strip() for tag in payload.tags if tag.strip()],
        evidence_capabilities_json=classify_evidence_capabilities(payload.content),
        content_md=payload.content.strip(),
        source_title=payload.source_title.strip(),
        source_url=payload.source_url,
        license_note=payload.license_note.strip(),
        ability_weights_json=default_ability_weights(),
        needs_reembedding=True,
        status="published",
    )
    db.add(item)
    db.flush()
    try:
        replace_item_relations(
            db, item=item, relation_type="prerequisite", source_public_ids=payload.prerequisites
        )
        replace_item_relations(
            db, item=item, relation_type="related", source_public_ids=payload.related
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    affected_ids = related_knowledge_ids(db, item)
    impact = mark_affected_content(
        db,
        domain_code=item.domain_code,
        affected_knowledge_ids=affected_ids,
        reason="manual_import",
    )
    mark_domain_preparing(db, item.domain_code)

    db.commit()
    db.refresh(item)
    return ok(
        {
            "item": serialize_knowledge_item(item),
            "index_status": "needs_rebuild",
            "affected_knowledge_ids": sorted(affected_ids),
            "affected_learning_paths": impact["learning_paths"],
            "affected_resources": impact["resources"],
            "next_action": "rebuild_vector_index",
        }
    )


@router.patch("/items/{knowledge_id}", response_model=ApiResponse)
def update_knowledge_item(
    knowledge_id: str,
    payload: KnowledgeItemUpdate,
    db: Session = Depends(get_db),
) -> ApiResponse:
    item = db.scalar(select(KnowledgeItem).where(KnowledgeItem.public_id == knowledge_id))
    if item is None:
        raise HTTPException(status_code=404, detail=f"Knowledge item not found: {knowledge_id}")

    affected_ids = related_knowledge_ids(db, item)
    values = payload.model_dump(exclude_unset=True)
    field_mapping = {
        "name": "name",
        "category": "category",
        "difficulty": "difficulty",
        "content": "content_md",
        "source_title": "source_title",
        "source_url": "source_url",
        "license_note": "license_note",
    }
    for payload_name, model_name in field_mapping.items():
        if payload_name in values:
            value = values[payload_name]
            if isinstance(value, str):
                value = value.strip()
            setattr(item, model_name, value)
    if "tags" in values:
        item.tags_json = [tag.strip() for tag in values["tags"] if tag.strip()]
    if "content" in values:
        item.evidence_capabilities_json = classify_evidence_capabilities(item.content_md)

    try:
        if payload.prerequisites is not None:
            replace_item_relations(
                db,
                item=item,
                relation_type="prerequisite",
                source_public_ids=payload.prerequisites,
            )
        if payload.related is not None:
            replace_item_relations(
                db,
                item=item,
                relation_type="related",
                source_public_ids=payload.related,
            )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    item.needs_reembedding = True
    db.flush()
    affected_ids.update(related_knowledge_ids(db, item))
    mark_affected_questions_stale(
        db,
        domain_code=item.domain_code,
        knowledge_ids={item.public_id},
    )
    impact = mark_affected_content(
        db,
        domain_code=item.domain_code,
        affected_knowledge_ids=affected_ids,
        reason="knowledge_item_updated",
    )
    mark_domain_preparing(db, item.domain_code)
    db.commit()
    db.refresh(item)
    return ok(
        {
            "item": serialize_knowledge_item(item),
            "index_status": "needs_rebuild",
            "affected_knowledge_ids": sorted(affected_ids),
            "affected_learning_paths": impact["learning_paths"],
            "affected_resources": impact["resources"],
            "next_action": "rebuild_vector_index",
        }
    )


@router.get("/search", response_model=ApiResponse)
def search_knowledge(
    query: str = Query(min_length=1),
    domain_code: str = Query(...),
    n_results: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> ApiResponse:
    statement = (
        select(KnowledgeItem)
        .where(
            KnowledgeItem.domain_code == domain_code,
            KnowledgeItem.status == "published",
        )
        .where(KnowledgeItem.name.contains(query) | KnowledgeItem.content_md.contains(query))
        .order_by(KnowledgeItem.public_id)
        .limit(n_results)
    )
    matches = [
        {
            "id": item.public_id,
            "knowledge_id": item.public_id,
            "name": item.name,
            "category": item.category,
            "difficulty": item.difficulty,
            "source_title": item.source_title,
            "distance": None,
            "preview": item.content_md[:180],
        }
        for item in db.scalars(statement)
    ]

    return ok(
        {
            "domain_code": domain_code,
            "query": query,
            "matches": matches,
            "total": len(matches),
            "search_mode": "metadata_keyword",
            "rag": candidate_rag_status(domain_code),
        }
    )


@router.post("/rebuild-index", response_model=ApiResponse)
def rebuild_vector_index(
    background_tasks: BackgroundTasks,
    domain_code: str = Query(...),
    db: Session = Depends(get_db),
) -> ApiResponse:
    job = candidate_index_job.try_start(db, domain_code)
    if job is None:
        raise HTTPException(status_code=409, detail="候选索引正在重建中，请稍后再试")
    background_tasks.add_task(candidate_index_job.run_rebuild, job.id, domain_code)
    return ok({"job_id": job.id, "status": "running", "domain_code": domain_code})


@router.get("/rebuild-index/status", response_model=ApiResponse)
def rebuild_index_status(
    domain_code: str = Query(...), db: Session = Depends(get_db)
) -> ApiResponse:
    return ok(candidate_index_job.status(db, domain_code))
