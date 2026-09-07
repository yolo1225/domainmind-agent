"""Knowledge document upload lifecycle and background import entrypoint."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DomainChangeSet,
    KnowledgeDocument,
    KnowledgeItem,
)
from app.services.knowledge_update_service import mark_affected_content

KNOWLEDGE_STORAGE_ROOT = Path(__file__).resolve().parents[3] / "storage" / "knowledge"
MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_TYPES = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown", ".txt": "text"}


class KnowledgeDocumentError(ValueError):
    pass


def _safe_file_name(name: str) -> str:
    normalized = Path(name).name.strip()
    if not normalized:
        raise KnowledgeDocumentError("文件名不能为空")
    return re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", normalized)[:255]


def validate_upload(name: str, content: bytes) -> tuple[str, str]:
    safe_name = _safe_file_name(name)
    file_type = FILE_TYPES.get(Path(safe_name).suffix.lower())
    if file_type is None:
        raise KnowledgeDocumentError("仅支持 PDF、Markdown 和 TXT 文件")
    if not content:
        raise KnowledgeDocumentError("不能上传空文件")
    if len(content) > MAX_FILE_BYTES:
        raise KnowledgeDocumentError("单个文件不能超过 20MB")
    return safe_name, file_type


def create_document(
    db: Session,
    *,
    domain_code: str,
    original_name: str,
    content: bytes,
    mime_type: str,
    source_title: str,
    license_note: str,
    uploaded_by: str,
    change_set: DomainChangeSet | None = None,
    import_mode: str = "append",
    replaces_document: KnowledgeDocument | None = None,
) -> KnowledgeDocument:
    safe_name, file_type = validate_upload(original_name, content)
    if import_mode not in {"append", "replace"}:
        raise KnowledgeDocumentError("导入模式仅支持 append 或 replace")
    if import_mode == "replace" and replaces_document is None:
        raise KnowledgeDocumentError("replace 模式必须指定被替换的来源文档")
    if replaces_document is not None and (
        import_mode != "replace" or replaces_document.domain_code != domain_code
    ):
        raise KnowledgeDocumentError("替换目标必须属于当前领域且使用 replace 模式")
    if change_set is not None and change_set.domain_code != domain_code:
        raise KnowledgeDocumentError("变更集不属于当前领域")
    if change_set is not None and change_set.mode != import_mode:
        raise KnowledgeDocumentError("导入模式必须与变更集一致")
    digest = hashlib.sha256(content).hexdigest()
    duplicate = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.domain_code == domain_code,
            KnowledgeDocument.sha256 == digest,
            KnowledgeDocument.status.not_in({"deleted", "withdrawn"}),
        )
    )
    if duplicate is not None:
        raise KnowledgeDocumentError("当前领域已存在内容相同的文件")

    public_id = f"kdoc_{uuid4().hex[:16]}"
    directory = (KNOWLEDGE_STORAGE_ROOT / domain_code / public_id).resolve()
    root = KNOWLEDGE_STORAGE_ROOT.resolve()
    if root not in directory.parents:
        raise KnowledgeDocumentError("领域存储路径非法")
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / safe_name
    path.write_bytes(content)
    document = KnowledgeDocument(
        public_id=public_id,
        domain_code=domain_code,
        change_set_id=change_set.id if change_set else None,
        import_mode=import_mode,
        replaces_document_id=replaces_document.id if replaces_document else None,
        original_name=safe_name,
        stored_path=str(path.relative_to(root)),
        file_type=file_type,
        mime_type=mime_type or "application/octet-stream",
        size_bytes=len(content),
        sha256=digest,
        status="queued",
        source_title=(source_title.strip() or safe_name)[:255],
        license_note=(license_note.strip() or "管理员上传")[:255],
        uploaded_by=(uploaded_by.strip() or "demo_admin")[:64],
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _document_path(document: KnowledgeDocument) -> Path:
    if not document.stored_path:
        raise KnowledgeDocumentError("系统知识包没有物理文件")
    root = KNOWLEDGE_STORAGE_ROOT.resolve()
    path = (root / document.stored_path).resolve()
    if root not in path.parents:
        raise KnowledgeDocumentError("文档存储路径非法")
    return path


def retry_document(db: Session, document: KnowledgeDocument) -> None:
    if document.file_type == "seed_package":
        raise KnowledgeDocumentError("系统知识包不需要重新处理")
    if document.status not in {
        "failed", "needs_attention", "interrupted", "queued", "review_pending", "ready"
    }:
        raise KnowledgeDocumentError("只有已发布、失败或排队中的文件可以重新处理")
    document.status = "queued"
    document.error_summary = None
    db.commit()


def delete_document(db: Session, document: KnowledgeDocument) -> dict[str, object]:
    if document.file_type == "seed_package":
        raise KnowledgeDocumentError("系统内置知识包不能删除")
    if document.change_set_id is not None:
        from app.services.domain_change_set_service import (
            DomainChangeSetError,
            cancel_change_set,
        )

        change_set = db.get(DomainChangeSet, document.change_set_id)
        if change_set is not None and change_set.status != "activated":
            try:
                cancelled = cancel_change_set(db, change_set)
            except DomainChangeSetError as exc:
                raise KnowledgeDocumentError(str(exc)) from exc
            return {
                "document_id": document.public_id,
                "status": "withdrawn",
                "change_set_cancelled": True,
                "change_set_id": change_set.public_id,
                "staged_knowledge_items_removed": cancelled["staged_knowledge_items_removed"],
                "staged_questions_removed": cancelled["staged_questions_removed"],
                "question_runs_cancelled": cancelled["question_runs_cancelled"],
                "candidate_manifests": cancelled["candidate_manifests"],
            }
    processing_statuses = {
        "queued", "parsing", "extracting", "graph_generation", "graph_review", "validating",
        "staging", "indexing", "smoke_testing", "publishing",
    }
    if document.status in processing_statuses:
        from app.models import KnowledgeImportBatch, KnowledgeImportRun

        latest_run = db.scalar(
            select(KnowledgeImportRun)
            .where(KnowledgeImportRun.document_id == document.id)
            .order_by(KnowledgeImportRun.id.desc())
            .limit(1)
        )
        if latest_run is None or latest_run.status != "cancel_requested":
            raise KnowledgeDocumentError("文件正在处理中，请先中断任务后再删除")
        latest_run.status = "cancelled"
        latest_run.current_step = "cancelled"
        latest_run.error_code = "import_cancelled"
        latest_run.error_summary = "导入已取消"
        latest_run.lease_owner = None
        latest_run.lease_expires_at = None
        latest_run.finished_at = datetime.now(UTC)
        for batch in db.scalars(
            select(KnowledgeImportBatch).where(
                KnowledgeImportBatch.run_id == latest_run.id,
                KnowledgeImportBatch.status.in_(("pending", "running")),
            )
        ):
            batch.status = "cancelled"
            batch.error_code = "import_cancelled"
            batch.error_summary = "导入已取消"
            batch.lease_owner = None
            batch.lease_expires_at = None
        document.status = "cancelled"
        document.error_summary = "导入已取消"
        db.flush()
    from app.models import DiagnosticQuestion, KnowledgeItemSource

    sources = list(db.scalars(select(KnowledgeItemSource).where(
        KnowledgeItemSource.document_id == document.id,
        KnowledgeItemSource.status.in_(("staged", "published")),
    )))
    item_ids = {source.knowledge_item_id for source in sources}
    items = list(db.scalars(select(KnowledgeItem).where(KnowledgeItem.id.in_(item_ids)))) if item_ids else []
    shared_item_ids: set[int] = set()
    retired_item_ids: set[int] = set()
    if items:
        mark_affected_content(
            db,
            domain_code=document.domain_code,
            affected_knowledge_ids={item.public_id for item in items},
            reason="knowledge_document_withdrawn",
        )
        for item in items:
            remaining = db.scalar(select(KnowledgeItemSource.id).where(
                KnowledgeItemSource.knowledge_item_id == item.id,
                KnowledgeItemSource.document_id != document.id,
                KnowledgeItemSource.status.in_(("staged", "published")),
            ))
            (shared_item_ids if remaining is not None else retired_item_ids).add(item.id)
        db.flush()
    for source in sources:
        source.status = "withdrawn"
    if retired_item_ids:
        retired_questions = list(
            db.scalars(
                select(DiagnosticQuestion).where(
                    DiagnosticQuestion.knowledge_item_id.in_(retired_item_ids),
                    DiagnosticQuestion.status == "active",
                )
            )
        )
        for question in retired_questions:
            question.status = "disabled"
            question.disabled_at = datetime.now(UTC).replace(tzinfo=None)
            question.disabled_reason = "知识来源已撤回"
        for item in items:
            if item.id in retired_item_ids:
                item.status = "retired"
                item.needs_reembedding = True
    # Preserve import artifacts, chunks, questions and answer records for audit.
    # Candidate rebuilding excludes retired knowledge from the active collection.
    document.status = "withdrawn"
    document.deleted_at = datetime.now(UTC)
    document.error_summary = "来源已撤回，历史学习记录已保留"
    db.commit()
    return {
        "document_id": document.public_id,
        "status": "withdrawn",
        "sources_retracted": len(sources),
        "knowledge_retired": len(retired_item_ids),
        "knowledge_preserved_shared": len(shared_item_ids),
        "affected_knowledge": len(items),
    }


def serialize_document(document: KnowledgeDocument) -> dict[str, object]:
    return {
        "document_id": document.public_id,
        "domain_code": document.domain_code,
        "change_set_id": document.change_set_id,
        "import_mode": document.import_mode,
        "replaces_document_id": document.replaces_document_id,
        "original_name": document.original_name,
        "file_type": document.file_type,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "status": document.status,
        "error_summary": document.error_summary,
        "knowledge_item_count": document.knowledge_item_count,
        "chunk_count": document.chunk_count,
        "embedding_model": document.embedding_model,
        "source_title": document.source_title,
        "license_note": document.license_note,
        "uploaded_by": document.uploaded_by,
        "is_system": document.file_type in {"seed_package", "submission_fixture"},
        "indexed_at": document.indexed_at.isoformat() if document.indexed_at else None,
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }
