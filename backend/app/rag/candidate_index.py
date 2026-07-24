from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from chromadb.errors import NotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeItem, KnowledgeRelation
from app.rag.candidate_chunker import CHUNKER_VERSION, CandidateChunk, chunk_knowledge_item
from app.rag.candidate_manifest import (
    DISTANCE_METRIC,
    MANIFEST_SCHEMA_VERSION,
    CandidateIndexManifest,
    CandidateManifestError,
    CandidateManifestStore,
    compute_index_version,
)
from app.rag.embedding_provider import EmbeddingProvider
from app.scripts.validate_rag_seed import source_data_version


logger = logging.getLogger(__name__)


class CandidateIndexError(RuntimeError):
    pass


def _canonical_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _item_payload(item: KnowledgeItem) -> dict[str, Any]:
    return {
        "knowledge_id": item.public_id,
        "domain_code": item.domain_code,
        "name": item.name,
        "category": item.category,
        "difficulty": item.difficulty,
        "tags": list(item.tags_json or []),
        "content": item.content_md,
        "source_title": item.source_title,
        "source_url": item.source_url,
        "license_note": item.license_note,
    }


def database_source_snapshot(
    db: Session, items: list[KnowledgeItem]
) -> list[dict[str, Any]]:
    payloads = {item.id: _item_payload(item) for item in items}
    relations = list(
        db.scalars(select(KnowledgeRelation).order_by(KnowledgeRelation.id))
    )
    for relation in relations:
        owner = payloads.get(relation.target_item_id)
        referenced = payloads.get(relation.source_item_id)
        if owner is None or referenced is None:
            continue
        field = {
            "prerequisite": "prerequisites",
            "related": "related",
        }.get(relation.relation_type)
        if field is not None:
            owner.setdefault(field, []).append(referenced["knowledge_id"])
    return sorted(payloads.values(), key=lambda payload: payload["knowledge_id"])


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class CandidateIndexBuilder:
    def __init__(
        self,
        *,
        db: Session,
        chroma_client: Any,
        embedding_provider: EmbeddingProvider,
        manifest_store: CandidateManifestStore | None = None,
        now: Any | None = None,
    ) -> None:
        self.db = db
        self.client = chroma_client
        self.provider = embedding_provider
        self.manifests = manifest_store or CandidateManifestStore()
        self._now = now or (lambda: datetime.now(UTC))

    def _collection_exists(self, name: str) -> bool:
        try:
            self.client.get_collection(name=name)
        except (NotFoundError, ValueError):
            return False
        return True

    def _load_manifest(self, domain_code: str) -> CandidateIndexManifest | None:
        return self.manifests.load(
            domain_code, collection_exists=self._collection_exists
        )

    @staticmethod
    def _chunks_for(items: list[KnowledgeItem]) -> dict[str, list[CandidateChunk]]:
        return {
            item.public_id: chunk_knowledge_item(
                knowledge_id=item.public_id,
                name=item.name,
                category=item.category,
                difficulty=item.difficulty,
                tags=list(item.tags_json or []),
                content_md=item.content_md,
            )
            for item in items
        }

    @staticmethod
    def _item_hash(item: KnowledgeItem) -> str:
        return _canonical_hash(_item_payload(item))

    @staticmethod
    def _metadata_for(
        item: KnowledgeItem,
        chunk: CandidateChunk,
        *,
        chunk_count: int,
        item_hash: str,
        model: str,
        dimensions: int,
    ) -> dict[str, Any]:
        return {
            "domain_code": item.domain_code,
            "knowledge_id": item.public_id,
            "name": item.name,
            "category": item.category,
            "difficulty": item.difficulty,
            "tags": ",".join(item.tags_json or []),
            "source_title": item.source_title,
            "source_url": item.source_url or "",
            "license_note": item.license_note,
            "chunk_index": chunk.chunk_index,
            "chunk_count": chunk_count,
            "heading_path": json.dumps(chunk.heading_path, ensure_ascii=False),
            "item_content_hash": item_hash,
            "embedding_model": model,
            "embedding_dimensions": dimensions,
            "chunker_version": CHUNKER_VERSION,
        }

    @staticmethod
    def _records(collection: Any) -> list[dict[str, Any]]:
        result = collection.get(include=["documents", "metadatas", "embeddings"])
        ids = list(result.get("ids") or [])
        documents = list(result.get("documents") or [])
        metadatas = list(result.get("metadatas") or [])
        raw_embeddings = result.get("embeddings")
        embeddings = [] if raw_embeddings is None else list(raw_embeddings)
        if not (len(ids) == len(documents) == len(metadatas) == len(embeddings)):
            raise CandidateIndexError("candidate collection record arrays have different lengths")
        return [
            {
                "id": ids[index],
                "document": documents[index],
                "metadata": metadatas[index],
                "embedding": list(embeddings[index]),
            }
            for index in range(len(ids))
        ]

    @staticmethod
    def _validate_compatibility(
        manifest: CandidateIndexManifest, *, model: str
    ) -> None:
        mismatches: list[str] = []
        if manifest.embedding_model != model:
            mismatches.append("embedding_model")
        if manifest.distance_metric != DISTANCE_METRIC:
            mismatches.append("distance_metric")
        if manifest.chunker_version != CHUNKER_VERSION:
            mismatches.append("chunker_version")
        if mismatches:
            raise CandidateIndexError(
                "incremental candidate build is incompatible with the active index; "
                f"run with --reset (changed: {', '.join(mismatches)})"
            )

    def _changed_ids(
        self,
        *,
        items: list[KnowledgeItem],
        old_records: list[dict[str, Any]],
        manifest: CandidateIndexManifest,
    ) -> set[str]:
        old_hashes: dict[str, set[str]] = defaultdict(set)
        for record in old_records:
            metadata = record["metadata"] or {}
            old_hashes[str(metadata.get("knowledge_id", ""))].add(
                str(metadata.get("item_content_hash", ""))
            )
        try:
            watermark = datetime.fromisoformat(manifest.last_successful_sync_at)
        except ValueError as exc:
            raise CandidateManifestError("last_successful_sync_at is not ISO-8601") from exc
        watermark = _as_utc(watermark)

        changed: set[str] = set()
        for item in items:
            item_hash = self._item_hash(item)
            hashes = old_hashes.get(item.public_id, set())
            updated_after_watermark = bool(
                item.updated_at and _as_utc(item.updated_at) > watermark
            )
            if (
                item.needs_reembedding
                or updated_after_watermark
                or hashes != {item_hash}
            ):
                changed.add(item.public_id)
        return changed

    @staticmethod
    def _validate_vectors(vectors: list[list[float]]) -> int:
        if not vectors:
            raise CandidateIndexError("candidate index contains no embedding vectors")
        dimensions = len(vectors[0])
        if dimensions <= 0:
            raise CandidateIndexError("candidate embedding vectors are empty")
        if any(len(vector) != dimensions for vector in vectors):
            raise CandidateIndexError("candidate embedding dimensions are inconsistent")
        if any(not math.isfinite(float(value)) for vector in vectors for value in vector):
            raise CandidateIndexError("candidate embedding contains a non-finite value")
        return dimensions

    @staticmethod
    def _build_id() -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        return f"{timestamp}_{uuid.uuid4().hex[:8]}"

    def _create_collection(
        self,
        *,
        name: str,
        domain_code: str,
        source_version: str,
        index_version: str,
        dimensions: int,
    ) -> Any:
        return self.client.create_collection(
            name=name,
            configuration={"hnsw": {"space": DISTANCE_METRIC}},
            metadata={
                "domain_code": domain_code,
                "embedding_model": self.provider.model_name,
                "embedding_dimensions": dimensions,
                "distance_metric": DISTANCE_METRIC,
                "index_version": index_version,
                "source_data_version": source_version,
                "chunker_version": CHUNKER_VERSION,
            },
            embedding_function=None,
        )

    def _validate_collection(
        self,
        *,
        collection: Any,
        items: list[KnowledgeItem],
        chunks_by_id: dict[str, list[CandidateChunk]],
        dimensions: int,
    ) -> None:
        records = self._records(collection)
        expected_chunk_ids = {
            chunk.chunk_id for chunks in chunks_by_id.values() for chunk in chunks
        }
        actual_ids = [str(record["id"]) for record in records]
        if len(actual_ids) != len(set(actual_ids)):
            raise CandidateIndexError("candidate collection contains duplicate chunk IDs")
        if set(actual_ids) != expected_chunk_ids:
            raise CandidateIndexError("candidate collection chunk IDs do not match database content")
        if collection.count() != len(expected_chunk_ids):
            raise CandidateIndexError("candidate collection count does not match expected chunks")

        expected_knowledge_ids = {item.public_id for item in items}
        actual_knowledge_ids: set[str] = set()
        indexes: dict[str, list[int]] = defaultdict(list)
        for record in records:
            metadata = record["metadata"] or {}
            knowledge_id = str(metadata.get("knowledge_id", ""))
            actual_knowledge_ids.add(knowledge_id)
            indexes[knowledge_id].append(int(metadata.get("chunk_index", -1)))
            if not str(record["document"] or "").strip():
                raise CandidateIndexError("candidate collection contains a blank document")
            for field in ("source_title", "license_note"):
                if not str(metadata.get(field, "")).strip():
                    raise CandidateIndexError(f"candidate chunk is missing {field}")
            if metadata.get("embedding_model") != self.provider.model_name:
                raise CandidateIndexError("candidate chunk embedding_model is inconsistent")
            if int(metadata.get("embedding_dimensions", 0)) != dimensions:
                raise CandidateIndexError("candidate chunk embedding_dimensions is inconsistent")
            if metadata.get("chunker_version") != CHUNKER_VERSION:
                raise CandidateIndexError("candidate chunk chunker_version is inconsistent")
        if actual_knowledge_ids != expected_knowledge_ids:
            raise CandidateIndexError("candidate knowledge IDs do not match database knowledge IDs")
        for knowledge_id, values in indexes.items():
            if sorted(values) != list(range(len(chunks_by_id[knowledge_id]))):
                raise CandidateIndexError("candidate chunk indexes are not contiguous")
        actual_dimensions = self._validate_vectors(
            [record["embedding"] for record in records]
        )
        if actual_dimensions != dimensions:
            raise CandidateIndexError("stored candidate vector dimensions are inconsistent")

    def _cleanup_old_collections(self, *, domain_code: str, keep: set[str]) -> int:
        deleted = 0
        prefix = f"knowledge_{domain_code}_candidate_"
        for collection in self.client.list_collections():
            name = collection if isinstance(collection, str) else collection.name
            if name.startswith(prefix) and name not in keep:
                self.client.delete_collection(name=name)
                deleted += 1
        return deleted

    def build(self, *, domain_code: str = "ai_app_dev", reset: bool = False) -> dict[str, Any]:
        started = perf_counter()
        sync_time = _as_utc(self._now())
        items = list(
            self.db.scalars(
                select(KnowledgeItem)
                .where(KnowledgeItem.domain_code == domain_code)
                .order_by(KnowledgeItem.public_id)
            )
        )
        if not items:
            raise CandidateIndexError(f"no knowledge items found for domain_code={domain_code}")
        chunks_by_id = self._chunks_for(items)
        snapshot = database_source_snapshot(self.db, items)
        source_version = source_data_version(snapshot)
        manifest = self._load_manifest(domain_code)

        old_records: list[dict[str, Any]] = []
        changed_ids = {item.public_id for item in items}
        orphan_ids: set[str] = set()
        if not reset:
            if manifest is None:
                raise CandidateIndexError("candidate manifest is missing; run with --reset")
            self._validate_compatibility(manifest, model=self.provider.model_name)
            active = self.client.get_collection(name=manifest.active_collection)
            old_records = self._records(active)
            changed_ids = self._changed_ids(
                items=items, old_records=old_records, manifest=manifest
            )
            current_ids = {item.public_id for item in items}
            old_ids = {
                str((record["metadata"] or {}).get("knowledge_id", ""))
                for record in old_records
            }
            orphan_ids = old_ids - current_ids
            if (
                not changed_ids
                and not orphan_ids
                and manifest.source_data_version == source_version
            ):
                return {
                    "status": "unchanged",
                    "mode": "incremental",
                    "domain_code": domain_code,
                    "embedding_model": manifest.embedding_model,
                    "embedding_dimensions": manifest.embedding_dimensions,
                    "source_data_version": manifest.source_data_version,
                    "index_version": manifest.index_version,
                    "active_collection": manifest.active_collection,
                    "previous_collection": manifest.previous_collection,
                    "indexed_items": manifest.indexed_item_count,
                    "indexed_chunks": manifest.indexed_chunk_count,
                    "reused_chunks": manifest.indexed_chunk_count,
                    "reembedded_items": 0,
                    "orphan_items_removed": 0,
                    "old_collections_deleted": 0,
                    "duration_ms": round((perf_counter() - started) * 1000),
                }

        item_by_id = {item.public_id: item for item in items}
        reused_records = [
            record
            for record in old_records
            if str((record["metadata"] or {}).get("knowledge_id", ""))
            in item_by_id.keys() - changed_ids
        ]
        changed_chunks = [
            chunk
            for knowledge_id in sorted(changed_ids)
            for chunk in chunks_by_id[knowledge_id]
        ]
        new_vectors = self.provider.embed_texts(
            [chunk.embedding_text for chunk in changed_chunks]
        )
        all_vectors = [record["embedding"] for record in reused_records] + new_vectors
        dimensions = self._validate_vectors(all_vectors)
        if manifest is not None and not reset and dimensions != manifest.embedding_dimensions:
            raise CandidateIndexError(
                "incremental candidate embedding dimensions changed; run with --reset"
            )
        index_version = compute_index_version(
            domain_code=domain_code,
            source_data_version=source_version,
            embedding_model=self.provider.model_name,
            embedding_dimensions=dimensions,
            distance_metric=DISTANCE_METRIC,
            chunker_version=CHUNKER_VERSION,
        )
        collection_name = f"knowledge_{domain_code}_candidate_{self._build_id()}"
        collection = None
        try:
            collection = self._create_collection(
                name=collection_name,
                domain_code=domain_code,
                source_version=source_version,
                index_version=index_version,
                dimensions=dimensions,
            )
            if reused_records:
                collection.add(
                    ids=[record["id"] for record in reused_records],
                    documents=[record["document"] for record in reused_records],
                    metadatas=[record["metadata"] for record in reused_records],
                    embeddings=[record["embedding"] for record in reused_records],
                )
            if changed_chunks:
                new_metadatas = []
                for chunk in changed_chunks:
                    item = item_by_id[chunk.knowledge_id]
                    new_metadatas.append(
                        self._metadata_for(
                            item,
                            chunk,
                            chunk_count=len(chunks_by_id[item.public_id]),
                            item_hash=self._item_hash(item),
                            model=self.provider.model_name,
                            dimensions=dimensions,
                        )
                    )
                collection.add(
                    ids=[chunk.chunk_id for chunk in changed_chunks],
                    documents=[chunk.embedding_text for chunk in changed_chunks],
                    metadatas=new_metadatas,
                    embeddings=new_vectors,
                )
            self._validate_collection(
                collection=collection,
                items=items,
                chunks_by_id=chunks_by_id,
                dimensions=dimensions,
            )
            new_manifest = CandidateIndexManifest(
                schema_version=MANIFEST_SCHEMA_VERSION,
                active_collection=collection_name,
                previous_collection=(manifest.active_collection if manifest else None),
                domain_code=domain_code,
                embedding_model=self.provider.model_name,
                embedding_dimensions=dimensions,
                distance_metric=DISTANCE_METRIC,
                chunker_version=CHUNKER_VERSION,
                index_version=index_version,
                source_data_version=source_version,
                last_successful_sync_at=sync_time.isoformat(),
                indexed_item_count=len(items),
                indexed_chunk_count=collection.count(),
            )
            self.manifests.write(new_manifest)
        except Exception:
            if collection is not None:
                try:
                    self.client.delete_collection(name=collection_name)
                except Exception:
                    logger.exception(
                        "Failed to delete an unsuccessful candidate collection name=%s",
                        collection_name,
                    )
            raise

        keep = {collection_name}
        if manifest is not None:
            keep.add(manifest.active_collection)
        try:
            old_deleted = self._cleanup_old_collections(domain_code=domain_code, keep=keep)
        except Exception:
            old_deleted = 0
            logger.exception("Failed to clean older candidate collections domain=%s", domain_code)
        return {
            "status": "built",
            "mode": "full" if reset else "incremental",
            "domain_code": domain_code,
            "embedding_model": self.provider.model_name,
            "embedding_dimensions": dimensions,
            "source_data_version": source_version,
            "index_version": index_version,
            "active_collection": collection_name,
            "previous_collection": manifest.active_collection if manifest else None,
            "indexed_items": len(items),
            "indexed_chunks": collection.count(),
            "reused_chunks": len(reused_records),
            "reembedded_items": len(changed_ids),
            "orphan_items_removed": len(orphan_ids),
            "old_collections_deleted": old_deleted,
            "duration_ms": round((perf_counter() - started) * 1000),
        }
