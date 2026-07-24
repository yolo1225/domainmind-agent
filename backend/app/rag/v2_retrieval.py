from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.contracts import (
    RetrieveKnowledgeInput,
    RetrieveKnowledgeOutput,
    RetrievedChunk,
    RetrievalMatchType,
    RetrievalPurpose,
    SourceRef,
)
from app.models import KnowledgeItem, KnowledgeRelation
from app.rag.candidate_manifest import CandidateIndexManifest, CandidateManifestError, CandidateManifestStore
from app.rag.embedding_provider import EmbeddingProvider, EmbeddingProviderError


ALGORITHM_VERSION = "v2-candidate-retrieval-1.0"
MAX_EXPLICIT_CHUNKS = 3
MAX_RELATION_CANDIDATES = 24
MAX_RELATIONS_PER_SEED = 2
MATCH_PRECEDENCE = {
    RetrievalMatchType.PRIORITY: 0,
    RetrievalMatchType.PREREQUISITE: 1,
    RetrievalMatchType.RELATED: 2,
    RetrievalMatchType.DEPENDENT: 3,
    RetrievalMatchType.SEMANTIC: 4,
}
ROUTE_ORDERS = {
    "remedial": (
        RetrievalMatchType.PRIORITY,
        RetrievalMatchType.PREREQUISITE,
        RetrievalMatchType.RELATED,
        RetrievalMatchType.SEMANTIC,
        RetrievalMatchType.DEPENDENT,
    ),
    "consolidation": (
        RetrievalMatchType.PRIORITY,
        RetrievalMatchType.RELATED,
        RetrievalMatchType.PREREQUISITE,
        RetrievalMatchType.SEMANTIC,
        RetrievalMatchType.DEPENDENT,
    ),
    "challenge": (
        RetrievalMatchType.DEPENDENT,
        RetrievalMatchType.RELATED,
        RetrievalMatchType.PRIORITY,
        RetrievalMatchType.SEMANTIC,
        RetrievalMatchType.PREREQUISITE,
    ),
    "source_verification": (
        RetrievalMatchType.PRIORITY,
        RetrievalMatchType.PREREQUISITE,
        RetrievalMatchType.SEMANTIC,
        RetrievalMatchType.RELATED,
        RetrievalMatchType.DEPENDENT,
    ),
}


class V2RetrievalError(RuntimeError):
    """Raised when V2 retrieval cannot safely use its candidate index."""


@dataclass(slots=True)
class CandidateRecord:
    chunk_id: str
    document: str
    metadata: dict[str, Any]
    embedding: list[float] | None
    routes: set[RetrievalMatchType] = field(default_factory=set)
    similarity: float | None = None

    @property
    def knowledge_id(self) -> str:
        return str(self.metadata.get("knowledge_id", ""))


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_text(value)
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _cosine(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return None
    return _clamp(dot / (left_norm * right_norm))


class V2CandidateRetriever:
    """Deterministic V2 retrieval over the isolated real-embedding collection."""

    def __init__(
        self,
        *,
        db: Session,
        chroma_client: Any,
        embedding_provider: EmbeddingProvider,
        manifest_store: CandidateManifestStore | None = None,
        mode: str = "full",
    ) -> None:
        if mode not in {"full", "semantic-only", "explicit-only", "semantic+relation"}:
            raise ValueError(f"unsupported V2 retrieval mode: {mode}")
        self.db = db
        self.client = chroma_client
        self.provider = embedding_provider
        self.manifests = manifest_store or CandidateManifestStore()
        self.mode = mode

    def execute(self, request: RetrieveKnowledgeInput) -> RetrieveKnowledgeOutput:
        manifest, collection = self._active_collection(request.context.domain_code)
        query_text = self._build_query(request)
        query_vector = self._embed_query(query_text, manifest)
        warnings: list[str] = []
        explicit_ids = _ordered_unique(
            [
                *request.retrieval_plan.priority_knowledge_ids,
                *request.retrieval_plan.prerequisite_knowledge_ids,
            ]
        )
        candidates: dict[str, CandidateRecord] = {}
        valid_explicit_ids: list[str] = []

        if self.mode in {"full", "explicit-only"}:
            for knowledge_id in _ordered_unique(request.retrieval_plan.priority_knowledge_ids):
                records = self._explicit_records(
                    collection, manifest, request.context.domain_code, knowledge_id, warnings
                )
                if records:
                    valid_explicit_ids.append(knowledge_id)
                self._merge(candidates, records, RetrievalMatchType.PRIORITY)
            for knowledge_id in _ordered_unique(request.retrieval_plan.prerequisite_knowledge_ids):
                records = self._explicit_records(
                    collection, manifest, request.context.domain_code, knowledge_id, warnings
                )
                if records:
                    valid_explicit_ids.append(knowledge_id)
                self._merge(candidates, records, RetrievalMatchType.PREREQUISITE)
        else:
            valid_explicit_ids = self._existing_explicit_ids(
                request.context.domain_code, explicit_ids
            )

        if self.mode in {"full", "semantic+relation"}:
            related = self._relation_records(
                collection,
                manifest,
                request.context.domain_code,
                valid_explicit_ids,
                warnings,
            )
            for route, records in related.items():
                self._merge(candidates, records, route)

        if self.mode in {"full", "semantic-only", "semantic+relation"}:
            semantic_records = self._semantic_records(
                collection,
                manifest,
                request.context.domain_code,
                query_vector,
                warnings,
                request.retrieval_plan.n_results,
            )
            self._merge(candidates, semantic_records, RetrievalMatchType.SEMANTIC)

        self._score_candidates(candidates.values(), query_vector, manifest, request, warnings)
        output = self._assemble_output(
            request=request,
            query_text=query_text,
            candidates=candidates,
            explicit_ids=explicit_ids,
            warnings=warnings,
        )
        return RetrieveKnowledgeOutput.model_validate(output.model_dump())

    def _active_collection(self, domain_code: str) -> tuple[CandidateIndexManifest, Any]:
        try:
            manifest = self.manifests.load(
                domain_code,
                collection_exists=lambda name: self._collection_exists(name),
            )
        except CandidateManifestError as exc:
            raise V2RetrievalError(f"candidate manifest is invalid: {exc}") from exc
        if manifest is None:
            raise V2RetrievalError("candidate manifest is missing")
        try:
            collection = self.client.get_collection(name=manifest.active_collection)
        except Exception as exc:
            raise V2RetrievalError("candidate active collection is unavailable") from exc
        if collection.count() != manifest.indexed_chunk_count:
            raise V2RetrievalError("candidate collection count does not match manifest")
        metadata = dict(getattr(collection, "metadata", None) or {})
        expected = {
            "domain_code": manifest.domain_code,
            "embedding_model": manifest.embedding_model,
            "embedding_dimensions": manifest.embedding_dimensions,
            "distance_metric": manifest.distance_metric,
            "index_version": manifest.index_version,
            "chunker_version": manifest.chunker_version,
        }
        for metadata_field, value in expected.items():
            if metadata.get(metadata_field) != value:
                raise V2RetrievalError(
                    f"candidate collection metadata mismatch: {metadata_field}"
                )
        return manifest, collection

    def _collection_exists(self, name: str) -> bool:
        try:
            self.client.get_collection(name=name)
        except Exception:
            return False
        return True

    def _build_query(self, request: RetrieveKnowledgeInput) -> str:
        base_terms = [request.context.learning_goal, *request.retrieval_plan.query_terms]
        weak_terms = [
            term
            for weak in request.profile.weak_knowledge
            for term in (weak.name, weak.category)
        ]
        revision_terms = list(request.revision_plan.query_terms) if request.revision_plan else []
        terms = _ordered_unique([*base_terms, *weak_terms, *revision_terms])
        query = " ".join(terms)
        if len(query) <= 2000:
            return query
        revision_set = set(_ordered_unique(revision_terms))
        priority = [term for term in terms if term in revision_set]
        remainder = [term for term in terms if term not in revision_set]
        selected: list[str] = []
        for term in [*remainder, *priority]:
            proposed = " ".join([*selected, term])
            if len(proposed) <= 2000:
                selected.append(term)
        if not priority:
            return " ".join(selected)[:2000].strip()
        # Revision terms are contractual evidence for source verification; retain them first.
        selected = []
        for term in [*priority, *remainder]:
            proposed = " ".join([*selected, term])
            if len(proposed) <= 2000:
                selected.append(term)
        return " ".join(selected)[:2000].strip()

    def _embed_query(self, query_text: str, manifest: CandidateIndexManifest) -> list[float]:
        try:
            vectors = self.provider.embed_texts([query_text])
        except EmbeddingProviderError as exc:
            raise V2RetrievalError(f"candidate query embedding failed: {type(exc).__name__}") from exc
        except Exception as exc:
            raise V2RetrievalError(f"candidate query embedding failed: {type(exc).__name__}") from exc
        if len(vectors) != 1 or len(vectors[0]) != manifest.embedding_dimensions:
            raise V2RetrievalError("candidate query embedding dimensions do not match manifest")
        vector = [float(value) for value in vectors[0]]
        if not all(math.isfinite(value) for value in vector):
            raise V2RetrievalError("candidate query embedding contains non-finite values")
        return vector

    def _records_from_result(self, result: dict[str, Any]) -> list[CandidateRecord]:
        ids = list(result.get("ids") or [])
        documents = list(result.get("documents") or [])
        metadatas = list(result.get("metadatas") or [])
        raw_embeddings = result.get("embeddings")
        embeddings = [None] * len(ids) if raw_embeddings is None else list(raw_embeddings)
        if not (len(ids) == len(documents) == len(metadatas) == len(embeddings)):
            raise V2RetrievalError("candidate collection returned inconsistent record arrays")
        return [
            CandidateRecord(
                chunk_id=str(ids[index]),
                document=_clean_text(documents[index]),
                metadata=dict(metadatas[index] or {}),
                embedding=(None if embeddings[index] is None else list(embeddings[index])),
            )
            for index in range(len(ids))
        ]

    def _explicit_records(
        self,
        collection: Any,
        manifest: CandidateIndexManifest,
        domain_code: str,
        knowledge_id: str,
        warnings: list[str],
    ) -> list[CandidateRecord]:
        try:
            result = collection.get(
                where={"knowledge_id": knowledge_id},
                include=["documents", "metadatas", "embeddings"],
            )
        except Exception as exc:
            raise V2RetrievalError("candidate explicit lookup failed") from exc
        records = self._valid_records(
            self._records_from_result(result), manifest, domain_code, warnings
        )
        records.sort(key=lambda record: (int(record.metadata.get("chunk_index", 0)), record.chunk_id))
        if not records:
            self._warn(warnings, f"explicit_knowledge_unavailable:{knowledge_id}")
        return records[:MAX_EXPLICIT_CHUNKS]

    def _existing_explicit_ids(self, domain_code: str, ids: list[str]) -> list[str]:
        if not ids:
            return []
        items = self.db.scalars(
            select(KnowledgeItem.public_id)
            .where(KnowledgeItem.domain_code == domain_code, KnowledgeItem.public_id.in_(ids))
            .order_by(KnowledgeItem.public_id)
        )
        found = set(items)
        return [item_id for item_id in ids if item_id in found]

    def _relation_records(
        self,
        collection: Any,
        manifest: CandidateIndexManifest,
        domain_code: str,
        seed_ids: list[str],
        warnings: list[str],
    ) -> dict[RetrievalMatchType, list[CandidateRecord]]:
        if not seed_ids:
            return {}
        items = list(
            self.db.scalars(
                select(KnowledgeItem)
                .where(KnowledgeItem.domain_code == domain_code)
                .order_by(KnowledgeItem.public_id)
            )
        )
        by_db_id = {item.id: item for item in items}
        by_public_id = {item.public_id: item for item in items}
        seeds = {by_public_id[value].id for value in seed_ids if value in by_public_id}
        relations = list(
            self.db.scalars(
                select(KnowledgeRelation).order_by(
                    KnowledgeRelation.relation_type,
                    KnowledgeRelation.source_item_id,
                    KnowledgeRelation.target_item_id,
                    KnowledgeRelation.id,
                )
            )
        )
        route_ids: dict[RetrievalMatchType, list[str]] = defaultdict(list)
        truncated = False
        for seed_id in seed_ids:
            seed = by_public_id.get(seed_id)
            if seed is None:
                continue
            per_type: dict[RetrievalMatchType, list[str]] = defaultdict(list)
            for relation in relations:
                source = by_db_id.get(relation.source_item_id)
                target = by_db_id.get(relation.target_item_id)
                if source is None or target is None or source.id == target.id:
                    continue
                route: RetrievalMatchType | None = None
                candidate: KnowledgeItem | None = None
                if relation.relation_type == "prerequisite":
                    if relation.target_item_id == seed.id:
                        route, candidate = RetrievalMatchType.PREREQUISITE, source
                    elif relation.source_item_id == seed.id:
                        route, candidate = RetrievalMatchType.DEPENDENT, target
                elif relation.relation_type == "related":
                    if relation.source_item_id == seed.id:
                        route, candidate = RetrievalMatchType.RELATED, target
                    elif relation.target_item_id == seed.id:
                        route, candidate = RetrievalMatchType.RELATED, source
                if route is not None and candidate is not None and candidate.id not in seeds:
                    per_type[route].append(candidate.public_id)
            for route in (RetrievalMatchType.PREREQUISITE, RetrievalMatchType.DEPENDENT, RetrievalMatchType.RELATED):
                candidates = _ordered_unique(per_type[route])
                if len(candidates) > MAX_RELATIONS_PER_SEED:
                    truncated = True
                route_ids[route].extend(candidates[:MAX_RELATIONS_PER_SEED])
        total = 0
        output: dict[RetrievalMatchType, list[CandidateRecord]] = defaultdict(list)
        for route in (RetrievalMatchType.PREREQUISITE, RetrievalMatchType.DEPENDENT, RetrievalMatchType.RELATED):
            for knowledge_id in _ordered_unique(route_ids[route]):
                if total >= MAX_RELATION_CANDIDATES:
                    truncated = True
                    break
                records = self._explicit_records(collection, manifest, domain_code, knowledge_id, warnings)
                output[route].extend(records)
                total += 1
        if truncated:
            self._warn(warnings, "relation_candidates_truncated")
        return output

    def _semantic_records(
        self,
        collection: Any,
        manifest: CandidateIndexManifest,
        domain_code: str,
        query_vector: list[float],
        warnings: list[str],
        n_results: int,
    ) -> list[CandidateRecord]:
        count = collection.count()
        if count <= 0:
            raise V2RetrievalError("candidate collection is empty")
        try:
            result = collection.query(
                query_embeddings=[query_vector],
                n_results=min(count, max(24, n_results * 3)),
                include=["documents", "metadatas", "distances", "embeddings"],
            )
        except Exception as exc:
            raise V2RetrievalError("candidate semantic query failed") from exc
        records = self._records_from_query_result(result)
        valid = self._valid_records(records, manifest, domain_code, warnings)
        for record in valid:
            distance = record.metadata.pop("__distance__", None)
            if not isinstance(distance, (int, float)):
                self._warn(warnings, f"candidate_distance_invalid:{record.chunk_id}")
                record.similarity = None
            else:
                record.similarity = _clamp(1.0 - float(distance))
        return [record for record in valid if record.similarity is not None]

    def _records_from_query_result(self, result: dict[str, Any]) -> list[CandidateRecord]:
        def first(key: str) -> list[Any]:
            values = result.get(key)
            if values is None or len(values) == 0:
                return []
            first_value = values[0]
            return [] if first_value is None else list(first_value)

        ids, documents, metadatas, distances = (
            first("ids"),
            first("documents"),
            first("metadatas"),
            first("distances"),
        )
        raw_embeddings = first("embeddings") if result.get("embeddings") is not None else [None] * len(ids)
        if not (len(ids) == len(documents) == len(metadatas) == len(distances) == len(raw_embeddings)):
            raise V2RetrievalError("candidate semantic query returned inconsistent arrays")
        records: list[CandidateRecord] = []
        for index, chunk_id in enumerate(ids):
            metadata = dict(metadatas[index] or {})
            metadata["__distance__"] = distances[index]
            records.append(
                CandidateRecord(
                    chunk_id=str(chunk_id),
                    document=_clean_text(documents[index]),
                    metadata=metadata,
                    embedding=(None if raw_embeddings[index] is None else list(raw_embeddings[index])),
                )
            )
        return records

    def _valid_records(
        self,
        records: list[CandidateRecord],
        manifest: CandidateIndexManifest,
        domain_code: str,
        warnings: list[str],
    ) -> list[CandidateRecord]:
        valid: list[CandidateRecord] = []
        for record in records:
            metadata = record.metadata
            if not record.chunk_id or not record.document:
                self._warn(warnings, "candidate_chunk_missing_content")
                continue
            if metadata.get("domain_code") != domain_code:
                self._warn(warnings, f"candidate_cross_domain:{record.chunk_id}")
                continue
            if metadata.get("embedding_model") != manifest.embedding_model:
                self._warn(warnings, f"candidate_model_mismatch:{record.chunk_id}")
                continue
            if int(metadata.get("embedding_dimensions", 0)) != manifest.embedding_dimensions:
                self._warn(warnings, f"candidate_dimensions_mismatch:{record.chunk_id}")
                continue
            if not _clean_text(metadata.get("knowledge_id")):
                self._warn(warnings, f"candidate_missing_knowledge_id:{record.chunk_id}")
                continue
            if not _clean_text(metadata.get("name")) or not _clean_text(metadata.get("category")):
                self._warn(warnings, f"candidate_missing_display_metadata:{record.chunk_id}")
                continue
            try:
                difficulty = int(metadata.get("difficulty", 0))
            except (TypeError, ValueError):
                difficulty = 0
            if difficulty not in {1, 2, 3, 4, 5}:
                self._warn(warnings, f"candidate_difficulty_invalid:{record.chunk_id}")
                continue
            if not _clean_text(metadata.get("source_title")) or not _clean_text(metadata.get("license_note")):
                self._warn(warnings, f"candidate_missing_source:{record.chunk_id}")
                continue
            if record.embedding is not None:
                try:
                    record.embedding = [float(value) for value in record.embedding]
                except (TypeError, ValueError):
                    self._warn(warnings, f"candidate_embedding_invalid:{record.chunk_id}")
                    continue
                if len(record.embedding) != manifest.embedding_dimensions or not all(
                    math.isfinite(value) for value in record.embedding
                ):
                    self._warn(warnings, f"candidate_embedding_invalid:{record.chunk_id}")
                    continue
            valid.append(record)
        return valid

    @staticmethod
    def _merge(
        candidates: dict[str, CandidateRecord],
        records: Iterable[CandidateRecord],
        route: RetrievalMatchType,
    ) -> None:
        for record in records:
            current = candidates.get(record.chunk_id)
            if current is None:
                record.routes.add(route)
                candidates[record.chunk_id] = record
            else:
                current.routes.add(route)
                if record.embedding is not None:
                    current.embedding = record.embedding
                if record.similarity is not None:
                    current.similarity = record.similarity

    def _score_candidates(
        self,
        candidates: Iterable[CandidateRecord],
        query_vector: list[float],
        manifest: CandidateIndexManifest,
        request: RetrieveKnowledgeInput,
        warnings: list[str],
    ) -> None:
        for record in candidates:
            if record.similarity is None:
                if record.embedding is None:
                    self._warn(warnings, f"candidate_embedding_missing:{record.chunk_id}")
                    record.routes.clear()
                    continue
                similarity = _cosine(query_vector, record.embedding)
                if similarity is None:
                    self._warn(warnings, f"candidate_cosine_invalid:{record.chunk_id}")
                    record.routes.clear()
                    continue
                record.similarity = similarity

    def _assemble_output(
        self,
        *,
        request: RetrieveKnowledgeInput,
        query_text: str,
        candidates: dict[str, CandidateRecord],
        explicit_ids: list[str],
        warnings: list[str],
    ) -> RetrieveKnowledgeOutput:
        available = [record for record in candidates.values() if record.routes and record.similarity is not None]
        route_order = ROUTE_ORDERS[
            "source_verification"
            if request.purpose == RetrievalPurpose.SOURCE_VERIFICATION
            else request.retrieval_plan.strategy.value
        ]
        route_scores = {route: 1.0 - index * 0.15 for index, route in enumerate(route_order)}

        def matched_by(record: CandidateRecord) -> RetrievalMatchType:
            return min(record.routes, key=lambda route: MATCH_PRECEDENCE[route])

        def score(record: CandidateRecord) -> tuple[float, float, float, str]:
            route = min(record.routes, key=lambda value: route_order.index(value))
            difficulty = int(record.metadata.get("difficulty", 1))
            target = request.retrieval_plan.target_difficulty
            difficulty_score = max(0.0, 1.0 - 0.20 * abs(difficulty - target))
            if request.purpose != RetrievalPurpose.SOURCE_VERIFICATION:
                strategy = request.retrieval_plan.strategy.value
                if strategy == "remedial" and difficulty > target:
                    difficulty_score *= 0.5
                elif strategy == "challenge" and difficulty < target:
                    difficulty_score *= 0.5
            total = 0.50 * route_scores[route] + 0.35 * float(record.similarity) + 0.15 * difficulty_score
            return total, float(record.similarity), abs(difficulty - target), record.chunk_id

        ranked = sorted(available, key=lambda record: (-score(record)[0], -score(record)[1], score(record)[2], score(record)[3]))
        selected: list[CandidateRecord] = []
        selected_ids: set[str] = set()
        missing: list[str] = []
        explicit_order = _ordered_unique(
            [
                *request.retrieval_plan.priority_knowledge_ids,
                *request.retrieval_plan.prerequisite_knowledge_ids,
            ]
        )
        for knowledge_id in explicit_order:
            if len(selected) >= request.retrieval_plan.n_results:
                missing.append(knowledge_id)
                continue
            matches = [record for record in ranked if record.knowledge_id == knowledge_id]
            if not matches:
                missing.append(knowledge_id)
                continue
            chosen = matches[0]
            if chosen.chunk_id not in selected_ids:
                selected.append(chosen)
                selected_ids.add(chosen.chunk_id)
        if len(explicit_order) > request.retrieval_plan.n_results:
            self._warn(warnings, "explicit_plan_exceeds_output_budget")

        def append_ranked(*, allow_same_knowledge: bool) -> None:
            selected_knowledge = {record.knowledge_id for record in selected}
            for record in ranked:
                if len(selected) >= request.retrieval_plan.n_results:
                    return
                if record.chunk_id in selected_ids:
                    continue
                if not allow_same_knowledge and record.knowledge_id in selected_knowledge:
                    continue
                selected.append(record)
                selected_ids.add(record.chunk_id)
                selected_knowledge.add(record.knowledge_id)

        append_ranked(allow_same_knowledge=False)
        append_ranked(allow_same_knowledge=True)
        covered = _ordered_unique(record.knowledge_id for record in selected)
        missing = [value for value in _ordered_unique(missing) if value not in set(covered)]
        chunks = [
            RetrievedChunk(
                chunk_id=record.chunk_id,
                knowledge_id=record.knowledge_id,
                name=_clean_text(record.metadata.get("name")),
                category=_clean_text(record.metadata.get("category")),
                difficulty=int(record.metadata.get("difficulty", 1)),
                content=record.document,
                similarity=round(float(record.similarity), 8),
                matched_by=matched_by(record),
                used_for=request.purpose,
                source=SourceRef(
                    source_ref_id=record.chunk_id,
                    knowledge_id=record.knowledge_id,
                    source_title=_clean_text(record.metadata.get("source_title")),
                    source_url=_clean_text(record.metadata.get("source_url")) or None,
                    license_note=_clean_text(record.metadata.get("license_note")),
                ),
            )
            for record in selected
        ]
        return RetrieveKnowledgeOutput(
            task_id=request.task_id,
            query_text=query_text,
            chunks=chunks,
            covered_knowledge_ids=covered,
            missing_knowledge_ids=missing,
            warnings=_ordered_unique(warnings)[:20],
        )

    @staticmethod
    def _warn(warnings: list[str], message: str) -> None:
        if message not in warnings and len(warnings) < 20:
            warnings.append(message)
