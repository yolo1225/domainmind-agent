from __future__ import annotations

import hashlib
import math
import re


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")
DEFAULT_MOCK_EMBEDDING_DIMENSIONS = 384


def embedding_model_name(default: str | None = None) -> str:
    return default or "mock-deterministic-embedding"


def tokenize_for_embedding(text: str) -> list[str]:
    tokens = TOKEN_PATTERN.findall(text.lower())
    bigrams = [f"{tokens[index]}{tokens[index + 1]}" for index in range(len(tokens) - 1)]
    return tokens + bigrams


def deterministic_embedding(
    text: str,
    dimensions: int = DEFAULT_MOCK_EMBEDDING_DIMENSIONS,
) -> list[float]:
    vector = [0.0] * dimensions
    tokens = tokenize_for_embedding(text)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def embed_texts(
    texts: list[str],
    dimensions: int = DEFAULT_MOCK_EMBEDDING_DIMENSIONS,
) -> list[list[float]]:
    return [deterministic_embedding(text, dimensions=dimensions) for text in texts]
