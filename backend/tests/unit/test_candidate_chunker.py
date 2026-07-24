from app.rag.candidate_chunker import chunk_knowledge_item


def _chunk(content: str, *, max_chars: int = 800, overlap_chars: int = 100):
    return chunk_knowledge_item(
        knowledge_id="knowledge-a",
        name="测试知识",
        category="测试分类",
        difficulty=3,
        tags=["rag", "测试"],
        content_md=content,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )

def _assert_exact_overlap(chunks, overlap_chars: int) -> None:
    for previous, current in zip(chunks, chunks[1:]):
        overlap_size = min(overlap_chars, len(previous.content))
        assert current.content[:overlap_size] == previous.content[-overlap_size:]


def test_heading_stack_is_inherited_and_reset_by_level() -> None:
    chunks = _chunk(
        "# 一级\n\n第一段。\n\n## 二级\n\n第二段。\n\n# 新一级\n\n第三段。",
        max_chars=20,
        overlap_chars=4,
    )

    assert [chunk.heading_path for chunk in chunks] == [
        ("一级",),
        ("一级", "二级"),
        ("新一级",),
    ]
    assert "标题：一级 > 二级" in chunks[1].embedding_text
    assert all("#" not in chunk.content for chunk in chunks)
    _assert_exact_overlap(chunks, 4)


def test_short_paragraphs_remain_whole_and_chunks_stay_within_limit() -> None:
    paragraphs = ["甲" * 35, "乙" * 35, "丙" * 35]
    chunks = _chunk("\n\n".join(paragraphs), max_chars=80, overlap_chars=40)

    assert all(len(chunk.content) <= 80 for chunk in chunks)
    assert paragraphs[0] in chunks[0].content
    assert paragraphs[1] in chunks[0].content
    assert paragraphs[1] in chunks[1].content
    _assert_exact_overlap(chunks, 40)


def test_oversized_paragraph_prefers_sentence_boundaries() -> None:
    chunks = _chunk("第一句很完整。第二句也完整。第三句仍完整。", max_chars=14, overlap_chars=3)

    assert len(chunks) >= 2
    assert chunks[0].content.endswith("。")
    assert all(len(chunk.content) <= 14 for chunk in chunks)
    _assert_exact_overlap(chunks, 3)


def test_text_without_sentence_boundaries_is_hard_split() -> None:
    chunks = _chunk("甲" * 205, max_chars=80, overlap_chars=10)

    assert [len(chunk.content) for chunk in chunks] == [80, 80, 65]
    _assert_exact_overlap(chunks, 10)


def test_overlong_sentence_keeps_overlap_within_limit() -> None:
    chunks = _chunk("甲" * 205 + "。", max_chars=80, overlap_chars=10)

    assert all(len(chunk.content) <= 80 for chunk in chunks)
    _assert_exact_overlap(chunks, 10)


def test_chunking_is_deterministic() -> None:
    content = "# 标题\n\n" + "段落内容。" * 200

    first = _chunk(content)
    second = _chunk(content)

    assert first == second
    assert [chunk.chunk_id for chunk in first] == [
        f"knowledge-a::chunk::{index}" for index in range(len(first))
    ]
    assert len(first) > 1
    assert all(len(chunk.content) <= 800 for chunk in first)
