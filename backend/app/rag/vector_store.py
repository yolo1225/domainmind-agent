from collections.abc import Sequence
from typing import Any

import chromadb
from chromadb.errors import NotFoundError

from app.core.config import settings


class VectorStore:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self.host = host if host is not None else settings.chroma_host
        self.port = port or settings.chroma_port
        if not self.host:
            raise ValueError("CHROMA_HOST is required; ChromaDB runs as an independent service")
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = chromadb.HttpClient(host=self.host, port=self.port)
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

    def delete_knowledge_chunks(
        self, *, domain_code: str, knowledge_ids: Sequence[str]
    ) -> int:
        normalized = sorted({item for item in knowledge_ids if item})
        if not normalized:
            return 0
        collection = self.get_collection(domain_code)
        where: dict[str, Any]
        if len(normalized) == 1:
            where = {"knowledge_id": normalized[0]}
        else:
            where = {"knowledge_id": {"$in": normalized}}
        existing = collection.get(where=where, include=["metadatas"])
        existing_ids = existing.get("ids", [])
        collection.delete(where=where)
        return len(existing_ids)

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
        result: dict[str, str | int] = {
            "status": "ok",
            "collections": len(collections),
        }
        result["mode"] = "http"
        result["host"] = self.host
        result["port"] = self.port
        return result

    def connection_info(self) -> dict[str, str | int]:
        return {"mode": "http", "host": self.host, "port": self.port}


def get_vector_store() -> VectorStore:
    return VectorStore()
