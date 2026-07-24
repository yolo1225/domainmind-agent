from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA_VERSION = "candidate-index-manifest-v1"
DISTANCE_METRIC = "cosine"


class CandidateManifestError(ValueError):
    pass


def candidate_index_root() -> Path:
    configured = os.getenv("CANDIDATE_INDEX_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "storage" / "candidate-index"


def compute_index_version(
    *,
    domain_code: str,
    source_data_version: str,
    embedding_model: str,
    embedding_dimensions: int,
    distance_metric: str,
    chunker_version: str,
) -> str:
    payload = {
        "chunker_version": chunker_version,
        "distance_metric": distance_metric,
        "domain_code": domain_code,
        "embedding_dimensions": embedding_dimensions,
        "embedding_model": embedding_model,
        "source_data_version": source_data_version,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


@dataclass(frozen=True, slots=True)
class CandidateIndexManifest:
    schema_version: str
    active_collection: str
    previous_collection: str | None
    domain_code: str
    embedding_model: str
    embedding_dimensions: int
    distance_metric: str
    chunker_version: str
    index_version: str
    source_data_version: str
    last_successful_sync_at: str
    indexed_item_count: int
    indexed_chunk_count: int

    def validate(self) -> None:
        required_strings = {
            "schema_version": self.schema_version,
            "active_collection": self.active_collection,
            "domain_code": self.domain_code,
            "embedding_model": self.embedding_model,
            "chunker_version": self.chunker_version,
            "index_version": self.index_version,
            "source_data_version": self.source_data_version,
            "last_successful_sync_at": self.last_successful_sync_at,
        }
        for field, value in required_strings.items():
            if not isinstance(value, str) or not value.strip():
                raise CandidateManifestError(f"{field} must be a non-empty string")
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise CandidateManifestError(
                f"unsupported manifest schema_version: {self.schema_version}"
            )
        if self.previous_collection is not None and (
            not isinstance(self.previous_collection, str)
            or not self.previous_collection.strip()
        ):
            raise CandidateManifestError("previous_collection must be null or non-empty")
        if self.previous_collection == self.active_collection:
            raise CandidateManifestError("active_collection and previous_collection must differ")
        if self.distance_metric != DISTANCE_METRIC:
            raise CandidateManifestError("distance_metric must be cosine")
        if (
            not isinstance(self.embedding_dimensions, int)
            or isinstance(self.embedding_dimensions, bool)
            or self.embedding_dimensions <= 0
        ):
            raise CandidateManifestError("embedding_dimensions must be a positive integer")
        for field, value in (
            ("indexed_item_count", self.indexed_item_count),
            ("indexed_chunk_count", self.indexed_chunk_count),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise CandidateManifestError(f"{field} must be a non-negative integer")
        for field, value in (
            ("index_version", self.index_version),
            ("source_data_version", self.source_data_version),
        ):
            digest = value.removeprefix("sha256:")
            if not value.startswith("sha256:") or len(digest) != 64:
                raise CandidateManifestError(f"{field} must be a sha256 digest")
            try:
                int(digest, 16)
            except ValueError as exc:
                raise CandidateManifestError(f"{field} must be a sha256 digest") from exc

        expected_index_version = compute_index_version(
            domain_code=self.domain_code,
            source_data_version=self.source_data_version,
            embedding_model=self.embedding_model,
            embedding_dimensions=self.embedding_dimensions,
            distance_metric=self.distance_metric,
            chunker_version=self.chunker_version,
        )
        if self.index_version != expected_index_version:
            raise CandidateManifestError("index_version does not match manifest inputs")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CandidateIndexManifest:
        expected_fields = set(cls.__dataclass_fields__)
        if set(payload) != expected_fields:
            missing = sorted(expected_fields - set(payload))
            extra = sorted(set(payload) - expected_fields)
            raise CandidateManifestError(
                f"manifest fields mismatch: missing={missing}, extra={extra}"
            )
        manifest = cls(**payload)
        manifest.validate()
        return manifest


class CandidateManifestStore:
    def __init__(
        self,
        *,
        root: Path | None = None,
        replace: Callable[[str | Path, str | Path], None] = os.replace,
    ) -> None:
        self.root = root or candidate_index_root()
        self._replace = replace

    def path_for(self, domain_code: str) -> Path:
        if not domain_code or any(character in domain_code for character in "/\\.."):
            raise CandidateManifestError("domain_code is not safe for a manifest path")
        return self.root / domain_code / "manifest.json"

    def load(
        self,
        domain_code: str,
        *,
        collection_exists: Callable[[str], bool] | None = None,
    ) -> CandidateIndexManifest | None:
        path = self.path_for(domain_code)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CandidateManifestError(f"cannot read candidate manifest: {type(exc).__name__}") from exc
        if not isinstance(payload, dict):
            raise CandidateManifestError("candidate manifest must be a JSON object")
        manifest = CandidateIndexManifest.from_dict(payload)
        if manifest.domain_code != domain_code:
            raise CandidateManifestError("manifest domain_code does not match requested domain")
        if collection_exists is not None and not collection_exists(manifest.active_collection):
            raise CandidateManifestError("manifest active_collection does not exist")
        return manifest

    def write(self, manifest: CandidateIndexManifest) -> Path:
        payload = manifest.to_dict()
        path = self.path_for(manifest.domain_code)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return path
