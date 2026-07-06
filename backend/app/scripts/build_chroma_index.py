from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import KnowledgeItem
from app.rag.chunker import chunk_markdown
from app.rag.embeddings import embed_texts, embedding_model_name
from app.rag.vector_store import VectorStore


def build_document(item: KnowledgeItem, chunk: str) -> str:
    tags = "、".join(item.tags_json or [])
    return (
        f"知识点：{item.name}\n"
        f"分类：{item.category}\n"
        f"难度：{item.difficulty}\n"
        f"标签：{tags}\n\n"
        f"{chunk}"
    )


def metadata_for(item: KnowledgeItem, chunk_index: int, chunk_count: int) -> dict[str, Any]:
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
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "embedding_model": embedding_model_name(),
    }


def build_index(domain_code: str = "ai_app_dev", reset: bool = False) -> dict[str, Any]:
    vector_store = VectorStore()
    if reset:
        vector_store.reset_collection(domain_code)

    with SessionLocal() as db:
        items = list(
            db.scalars(
                select(KnowledgeItem)
                .where(KnowledgeItem.domain_code == domain_code)
                .order_by(KnowledgeItem.public_id)
            )
        )
        if not items:
            raise RuntimeError(f"No knowledge items found for domain_code={domain_code}")

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for item in items:
            chunks = chunk_markdown(item.content_md)
            for index, chunk in enumerate(chunks):
                ids.append(f"{item.public_id}::chunk::{index}")
                documents.append(build_document(item, chunk))
                metadatas.append(metadata_for(item, index, len(chunks)))

        embeddings = embed_texts(documents)
        vector_store.upsert_chunks(
            domain_code=domain_code,
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

        for item in items:
            item.needs_reembedding = False
        db.commit()

    collection = vector_store.get_collection(domain_code)
    return {
        "domain_code": domain_code,
        "collection_name": vector_store.collection_name(domain_code),
        "embedding_model": embedding_model_name(),
        "indexed_items": len(items),
        "indexed_chunks": len(ids),
        "collection_count": collection.count(),
        "persist_directory": vector_store.persist_directory,
    }


def query_index(domain_code: str, query: str, n_results: int) -> dict[str, Any]:
    vector_store = VectorStore()
    result = vector_store.query(
        domain_code=domain_code,
        query_embeddings=embed_texts([query]),
        n_results=n_results,
    )
    matches: list[dict[str, Any]] = []
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    for index, item_id in enumerate(ids):
        metadata = metadatas[index]
        matches.append(
            {
                "id": item_id,
                "knowledge_id": metadata.get("knowledge_id"),
                "name": metadata.get("name"),
                "distance": distances[index],
                "preview": documents[index][:120],
            }
        )
    return {"query": query, "matches": matches}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ChromaDB index for knowledge items.")
    parser.add_argument("--domain-code", default="ai_app_dev")
    parser.add_argument("--reset", action="store_true", help="Delete and rebuild the domain collection.")
    parser.add_argument("--query", help="Run a smoke-test query after indexing.")
    parser.add_argument("--n-results", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary.")
    args = parser.parse_args()

    summary = build_index(domain_code=args.domain_code, reset=args.reset)
    if args.query:
        summary["query_result"] = query_index(args.domain_code, args.query, args.n_results)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            "Chroma index complete: "
            f"{summary['indexed_items']} items, "
            f"{summary['indexed_chunks']} chunks, "
            f"collection_count={summary['collection_count']}."
        )


if __name__ == "__main__":
    main()
