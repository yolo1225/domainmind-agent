from __future__ import annotations

import argparse
import json
import time

from app.rag.embedding_provider import EmbeddingProviderError, OpenAICompatibleEmbeddingProvider


SAFE_SMOKE_TEXTS = [
    "人工智能应用开发需要可验证的数据与模型流程。",
    "检索增强生成应保留知识来源。",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the live embedding provider safely.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Required explicit opt-in because this command performs a paid external request.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; no fixture or mock fallback is available")

    started = time.perf_counter()
    try:
        provider = OpenAICompatibleEmbeddingProvider()
        vectors = provider.embed_texts(SAFE_SMOKE_TEXTS)
        result = {
            "status": "passed",
            "mode": "live",
            "model_name": provider.model_name,
            "input_count": len(SAFE_SMOKE_TEXTS),
            "vector_count": len(vectors),
            "dimensions": len(vectors[0]),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    except EmbeddingProviderError as exc:
        result = {
            "status": "failed",
            "mode": "live",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Embedding provider check failed: {result['error_type']}: {result['error']}")
        raise SystemExit(1) from exc

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "Embedding provider check passed: "
            f"model={result['model_name']}, dimensions={result['dimensions']}, "
            f"latency={result['latency_ms']}ms."
        )


if __name__ == "__main__":
    main()
