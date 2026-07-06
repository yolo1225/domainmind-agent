from collections.abc import Sequence
from pathlib import Path
from typing import Any

import chromadb
from chromadb.errors import NotFoundError

from app.core.config import settings


class VectorStore:
    def __init__(self, persist_directory: str | None = None) -> None:
        self.persist_directory = persist_directory or settings.resolved_chroma_persist_directory
        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = chromadb.PersistentClient(path=self.persist_directory)
        return self._client

    def collection_name(self, domain_code: str) -> str:
        return f"knowledge_{domain_code}"

    def get_collection(self, domain_code: str) -> Any:
        return self.client.get_or_create_collection(
            name=self.collection_name(domain_code),
            metadata={"domain_code": domain_code},
        )

    def upsert_chunks(
        self,
        *,
        domain_code: str,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        documents: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
    ) -> None:
        collection = self.get_collection(domain_code)
        collection.upsert(
            ids=list(ids),
            embeddings=[list(item) for item in embeddings],
            documents=list(documents),
            metadatas=list(metadatas),
        )

    def query(
        self,
        *,
        domain_code: str,
        query_embeddings: Sequence[Sequence[float]],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        collection = self.get_collection(domain_code)
        return collection.query(
            query_embeddings=[list(item) for item in query_embeddings],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    def reset_collection(self, domain_code: str) -> None:
        collection_name = self.collection_name(domain_code)
        try:
            self.client.delete_collection(collection_name)
        except (NotFoundError, ValueError):
            return

    def health_check(self) -> dict[str, str | int]:
        collections = self.client.list_collections()
        return {
            "status": "ok",
            "persist_directory": self.persist_directory,
            "collections": len(collections),
        }


def get_vector_store() -> VectorStore:
    return VectorStore()
