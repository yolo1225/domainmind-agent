from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import DiagnosticQuestion, Domain, KnowledgeItem
from app.rag.vector_store import VectorStore
from app.schemas.common import ApiResponse, ok

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_domains(db: Session = Depends(get_db)) -> ApiResponse:
    domains = list(db.scalars(select(Domain).order_by(Domain.domain_code)))
    return ok(
        [
            {
                "domain_code": domain.domain_code,
                "name": domain.name,
                "domain_schema_version": domain.schema_version,
                "status": "active",
                "config": domain.config_json,
            }
            for domain in domains
        ]
    )


@router.get("/{domain_code}/validate", response_model=ApiResponse)
def validate_domain_config(
    domain_code: str,
    db: Session = Depends(get_db),
) -> ApiResponse:
    knowledge_count = (
        db.scalar(
            select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.domain_code == domain_code)
        )
        or 0
    )
    question_count = (
        db.scalar(
            select(func.count())
            .select_from(DiagnosticQuestion)
            .where(DiagnosticQuestion.domain_code == domain_code)
        )
        or 0
    )
    vector_store = VectorStore()
    vector_count = vector_store.get_collection(domain_code).count()

    targets = {
        "knowledge_items": 50,
        "diagnostic_questions": 60,
        "vector_chunks": knowledge_count,
    }
    issues = []
    if knowledge_count < targets["knowledge_items"]:
        issues.append(
            {
                "level": "warning",
                "message": "知识点数量未达到 M1 目标",
                "actual": knowledge_count,
                "target": targets["knowledge_items"],
            }
        )
    if question_count < targets["diagnostic_questions"]:
        issues.append(
            {
                "level": "warning",
                "message": "诊断题数量未达到 M1 目标",
                "actual": question_count,
                "target": targets["diagnostic_questions"],
            }
        )
    if vector_count < targets["vector_chunks"]:
        issues.append(
            {
                "level": "warning",
                "message": "ChromaDB 向量数量少于知识切片数量",
                "actual": vector_count,
                "target": targets["vector_chunks"],
            }
        )

    return ok(
        {
            "domain_code": domain_code,
            "passed": not issues,
            "counts": {
                "knowledge_items": knowledge_count,
                "diagnostic_questions": question_count,
                "chroma_vectors": vector_count,
            },
            "targets": targets,
            "issues": issues,
        }
    )
