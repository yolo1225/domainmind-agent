from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import KnowledgeItem, LearningPath
from app.rag.embeddings import embed_texts, embedding_model_name
from app.rag.vector_store import VectorStore, get_vector_store
from app.schemas.common import ApiResponse, ok

router = APIRouter()


class KnowledgeItemCreate(BaseModel):
    domain_code: str = Field(default="ai_app_dev", min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(default="未分类", min_length=1, max_length=64)
    difficulty: int = Field(default=2, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    content: str = Field(min_length=10)
    source_title: str = Field(default="教师手动导入", min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=512)
    license_note: str = Field(default="manual-import", max_length=255)


def serialize_knowledge_item(item: KnowledgeItem) -> dict[str, Any]:
    return {
        "knowledge_id": item.public_id,
        "domain_code": item.domain_code,
        "name": item.name,
        "category": item.category,
        "difficulty": item.difficulty,
        "tags": item.tags_json or [],
        "content": item.content_md,
        "source_title": item.source_title,
        "source_url": item.source_url,
        "license_note": item.license_note,
        "needs_reembedding": item.needs_reembedding,
    }


@router.get("/items", response_model=ApiResponse)
def list_knowledge_items(
    domain_code: str = Query(default="ai_app_dev"),
    category: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ApiResponse:
    filters = [KnowledgeItem.domain_code == domain_code]
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
        raise HTTPException(status_code=409, detail=f"Knowledge item already exists: {payload.name}")

    item = KnowledgeItem(
        public_id=f"ki_{uuid4().hex[:12]}",
        domain_code=payload.domain_code,
        name=payload.name.strip(),
        category=payload.category.strip(),
        difficulty=payload.difficulty,
        tags_json=[tag.strip() for tag in payload.tags if tag.strip()],
        content_md=payload.content.strip(),
        source_title=payload.source_title.strip(),
        source_url=payload.source_url,
        license_note=payload.license_note.strip(),
        needs_reembedding=True,
    )
    db.add(item)

    affected_paths = list(
        db.scalars(select(LearningPath).where(LearningPath.domain_code == payload.domain_code))
    )
    for path in affected_paths:
        path.needs_refresh = True
        path.path_json = {
            **(path.path_json or {}),
            "knowledge_update_reason": "manual_import",
            "changed_knowledge_name": item.name,
        }

    db.commit()
    db.refresh(item)
    return ok(
        {
            "item": serialize_knowledge_item(item),
            "index_status": "needs_rebuild",
            "affected_learning_paths": len(affected_paths),
            "next_action": "rebuild_vector_index",
        }
    )


@router.get("/search", response_model=ApiResponse)
def search_knowledge(
    query: str = Query(min_length=1),
    domain_code: str = Query(default="ai_app_dev"),
    n_results: int = Query(default=5, ge=1, le=20),
    vector_store: VectorStore = Depends(get_vector_store),
) -> ApiResponse:
    result = vector_store.query(
        domain_code=domain_code,
        query_embeddings=embed_texts([query]),
        n_results=n_results,
    )
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    matches = []
    for index, item_id in enumerate(ids):
        metadata = metadatas[index]
        matches.append(
            {
                "id": item_id,
                "knowledge_id": metadata.get("knowledge_id"),
                "name": metadata.get("name"),
                "category": metadata.get("category"),
                "difficulty": metadata.get("difficulty"),
                "source_title": metadata.get("source_title"),
                "distance": distances[index],
                "preview": documents[index][:180],
            }
        )

    return ok(
        {
            "domain_code": domain_code,
            "query": query,
            "matches": matches,
            "total": len(matches),
            "embedding_model": embedding_model_name(),
        }
    )


@router.post("/rebuild-index", response_model=ApiResponse)
def rebuild_vector_index() -> ApiResponse:
    return ok({"status": "queued", "affected_domain": "ai_app_dev"})
