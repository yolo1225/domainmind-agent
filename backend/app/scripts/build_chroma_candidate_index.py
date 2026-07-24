from __future__ import annotations

import argparse
import json

from app.core.db import SessionLocal
from app.rag.candidate_index import CandidateIndexBuilder
from app.rag.embedding_provider import OpenAICompatibleEmbeddingProvider
from app.rag.vector_store import VectorStore


def build_candidate_index(*, domain_code: str, reset: bool, live: bool) -> dict:
    if not live:
        raise RuntimeError("--live is required; candidate indexing never falls back to mock vectors")
    provider = OpenAICompatibleEmbeddingProvider()
    with SessionLocal() as db:
        return CandidateIndexBuilder(
            db=db,
            chroma_client=VectorStore().client,
            embedding_provider=provider,
        ).build(domain_code=domain_code, reset=reset)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the isolated real-embedding Chroma candidate index."
    )
    parser.add_argument("--domain-code", default="ai_app_dev")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = build_candidate_index(
            domain_code=args.domain_code,
            reset=args.reset,
            live=args.live,
        )
    except Exception as exc:
        error = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)}
        if args.json:
            print(json.dumps(error, ensure_ascii=False, indent=2))
        else:
            print(f"Candidate index build failed: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "Candidate index complete: "
            f"{result['indexed_items']} items, {result['indexed_chunks']} chunks, "
            f"active={result['active_collection']}."
        )


if __name__ == "__main__":
    main()
