from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.domain_evidence_policy import classify_evidence_capabilities
from app.models import KnowledgeDocument, KnowledgeImportCandidate, KnowledgeItem


SOURCE_KNOWLEDGE_PREFIX = re.compile(
    r"^.*?\([a-z][a-z0-9_-]*\)\s*[/／]\s*\d+\s*[.．、:-]?\s*",
    re.IGNORECASE,
)


def normalize_knowledge_name(value: str) -> str:
    normalized = SOURCE_KNOWLEDGE_PREFIX.sub("", value.strip()).strip()
    return normalized or value.strip()


def _candidate_id(document_id: str, candidate_type: str, stable_key: str) -> str:
    digest = hashlib.sha256(f"{document_id}:{candidate_type}:{stable_key}".encode()).hexdigest()[
        :16
    ]
    return f"kic_{digest}"


def replace_candidates(
    db: Session, document: KnowledgeDocument, sections: list[dict[str, Any]]
) -> list[KnowledgeImportCandidate]:
    db.execute(
        delete(KnowledgeImportCandidate).where(KnowledgeImportCandidate.document_id == document.id)
    )
    candidates: list[KnowledgeImportCandidate] = []
    knowledge_ids: list[str] = []
    external_to_candidate: dict[str, str] = {}
    for index, section in enumerate(sections, start=1):
        # The complete heading path remains in source_locator_json for
        # traceability. A knowledge item's display name is its own leaf
        # heading, so a document title never leaks into every node label.
        heading_path = list(section["heading_path"])
        heading = normalize_knowledge_name(str(heading_path[-1]))
        metadata = dict(section.get("metadata") or {})
        external_id = str(metadata.get("knowledge_id") or "").strip() or None
        public_id = _candidate_id(document.public_id, "knowledge_item", section["checksum"])
        knowledge_ids.append(public_id)
        if external_id:
            external_to_candidate[external_id] = public_id
        existing = None
        if external_id:
            existing = db.scalar(
                select(KnowledgeItem).where(
                    KnowledgeItem.domain_code == document.domain_code,
                    KnowledgeItem.external_id == external_id,
                )
            )
        if existing is None:
            existing = db.scalar(
                select(KnowledgeItem).where(
                    KnowledgeItem.domain_code == document.domain_code,
                    KnowledgeItem.name == heading,
                    KnowledgeItem.status == "published",
                )
            )
        target_public_id = existing.public_id if existing else (
            "ki_" + hashlib.sha256(
                f"{document.domain_code}:{external_id or section['checksum']}".encode()
            ).hexdigest()[:16]
        )
        before_checksum = (
            hashlib.sha256(existing.content_md.encode()).hexdigest() if existing else None
        )
        action = "create" if existing is None else (
            "skip" if before_checksum == section["checksum"] else "update"
        )
        evidence_capabilities = classify_evidence_capabilities(section["text"])
        explicit_weights = metadata.get("ability_weights")
        locator = {
            key: section.get(key) for key in ("heading_path", "page_start", "page_end", "checksum")
        }
        locator["chunk_id"] = section.get("chunk_public_id")
        knowledge = KnowledgeImportCandidate(
            public_id=public_id,
            document_id=document.id,
            domain_code=document.domain_code,
            candidate_type="knowledge_item",
            payload_json={
                "name": heading[:255],
                "external_id": external_id,
                "action": action,
                "target_public_id": target_public_id,
                "before_checksum": before_checksum,
                "after_checksum": section["checksum"],
                "source_chunk_ids": [section.get("chunk_public_id")],
                "category": str(metadata.get("category") or section["heading_path"][0])[:64],
                "content": section["text"],
                "difficulty": int(metadata.get("difficulty") or 2),
                "tags": metadata.get("tags") or ["document-import"],
                "ability_weights": explicit_weights,
                "ability_weight_source": "explicit" if explicit_weights else "missing",
                "ability_weight_confidence": 1.0 if explicit_weights else 0.0,
                "evidence_capabilities": evidence_capabilities,
                "source_quote": section["text"][:300],
                "source_title": metadata.get("source_title") or document.source_title,
                "source_url": metadata.get("source_url"),
                "license_note": metadata.get("license") or document.license_note,
                "prerequisites": metadata.get("prerequisites") or [],
            },
            source_locator_json=locator,
            confidence=0.85,
            status="pending",
            validation_errors_json=[],
        )
        # Formal questions are intentionally not generated during document
        # import.  They enter through the independently certified XLSX bank.
        candidates.append(knowledge)
    for section, target_candidate in zip(sections, knowledge_ids, strict=True):
        for prerequisite in (section.get("metadata") or {}).get("prerequisites", []):
            source_candidate = external_to_candidate.get(str(prerequisite))
            if not source_candidate:
                continue
            candidates.append(
                KnowledgeImportCandidate(
                    public_id=_candidate_id(
                        document.public_id, "knowledge_relation", f"{source_candidate}:{target_candidate}"
                    ),
                    document_id=document.id,
                    domain_code=document.domain_code,
                    candidate_type="knowledge_relation",
                    payload_json={
                        "source_candidate_id": source_candidate,
                        "target_candidate_id": target_candidate,
                        "relation_type": "prerequisite",
                        "reason": "结构化 prerequisites 字段",
                        "generation_method": "explicit",
                        "evidence_chunk_ids": [section.get("chunk_public_id")],
                    },
                    source_locator_json={"chunk_id": section.get("chunk_public_id"), "checksum": section["checksum"]},
                    confidence=1.0,
                    status="pending",
                    validation_errors_json=[],
                )
            )
    db.add_all(candidates)
    return candidates
