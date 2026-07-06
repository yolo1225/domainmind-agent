def rank_chunks(chunks: list[dict]) -> list[dict]:
    return sorted(chunks, key=lambda item: item.get("similarity", 0), reverse=True)
