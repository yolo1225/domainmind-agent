from app.rag.embeddings import deterministic_embedding, embed_texts, tokenize_for_embedding


def test_deterministic_embedding_is_stable_and_normalized() -> None:
    first = deterministic_embedding("RAG 文档切片")
    second = deterministic_embedding("RAG 文档切片")

    assert first == second
    assert len(first) == 384
    assert round(sum(value * value for value in first), 6) == 1


def test_embed_texts_and_tokenizer_handle_chinese_terms() -> None:
    tokens = tokenize_for_embedding("Prompt 输出格式")
    embeddings = embed_texts(["Prompt 输出格式", "RAG 检索"])

    assert "prompt" in tokens
    assert "输" in tokens
    assert len(embeddings) == 2
