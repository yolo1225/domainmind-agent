import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.rag.candidate_manifest import (
    DISTANCE_METRIC,
    MANIFEST_SCHEMA_VERSION,
    CandidateIndexManifest,
    CandidateManifestError,
    CandidateManifestStore,
    compute_index_version,
)


SOURCE_VERSION = "sha256:" + "1" * 64


def _manifest(**overrides) -> CandidateIndexManifest:
    values = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "active_collection": "knowledge_ai_app_dev_candidate_new",
        "previous_collection": "knowledge_ai_app_dev_candidate_old",
        "domain_code": "ai_app_dev",
        "embedding_model": "test-model",
        "embedding_dimensions": 3,
        "distance_metric": DISTANCE_METRIC,
        "chunker_version": "chunker-v1",
        "source_data_version": SOURCE_VERSION,
        "last_successful_sync_at": "2026-07-24T12:00:00+00:00",
        "indexed_item_count": 50,
        "indexed_chunk_count": 53,
    }
    values.update(overrides)
    values.setdefault(
        "index_version",
        compute_index_version(
            domain_code=values["domain_code"],
            source_data_version=values["source_data_version"],
            embedding_model=values["embedding_model"],
            embedding_dimensions=values["embedding_dimensions"],
            distance_metric=values["distance_metric"],
            chunker_version=values["chunker_version"],
        ),
    )
    return CandidateIndexManifest(**values)


def test_index_version_is_deterministic_and_input_sensitive() -> None:
    first = _manifest().index_version
    assert _manifest().index_version == first
    assert _manifest(embedding_dimensions=4).index_version != first


def test_manifest_round_trip_and_active_collection_check(tmp_path: Path) -> None:
    store = CandidateManifestStore(root=tmp_path)
    path = store.write(_manifest())

    assert path == tmp_path / "ai_app_dev" / "manifest.json"
    loaded = store.load(
        "ai_app_dev", collection_exists=lambda name: name.endswith("_new")
    )
    assert loaded == _manifest()

    with pytest.raises(CandidateManifestError, match="does not exist"):
        store.load("ai_app_dev", collection_exists=lambda _: False)


def test_manifest_rejects_unknown_fields_and_invalid_metric(tmp_path: Path) -> None:
    store = CandidateManifestStore(root=tmp_path)
    path = store.write(_manifest())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unknown"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CandidateManifestError, match="fields mismatch"):
        store.load("ai_app_dev")

    with pytest.raises(CandidateManifestError, match="cosine"):
        replace(_manifest(), distance_metric="l2").validate()


def test_failed_replace_preserves_previous_manifest(tmp_path: Path) -> None:
    good_store = CandidateManifestStore(root=tmp_path)
    path = good_store.write(_manifest())
    original = path.read_bytes()

    def fail_replace(_source, _target) -> None:
        raise OSError("simulated replace failure")

    failing_store = CandidateManifestStore(root=tmp_path, replace=fail_replace)
    with pytest.raises(OSError, match="simulated"):
        failing_store.write(
            _manifest(
                active_collection="knowledge_ai_app_dev_candidate_next",
                previous_collection="knowledge_ai_app_dev_candidate_new",
            )
        )

    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.tmp"))
