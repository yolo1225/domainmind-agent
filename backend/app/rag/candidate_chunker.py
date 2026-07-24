from __future__ import annotations

import re
from dataclasses import dataclass


CHUNKER_VERSION = "candidate-heading-v2"
DEFAULT_MAX_CHARS = 800
DEFAULT_OVERLAP_CHARS = 100

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;\.])")


@dataclass(frozen=True, slots=True)
class CandidateChunk:
    chunk_id: str
    knowledge_id: str
    chunk_index: int
    heading_path: tuple[str, ...]
    content: str
    embedding_text: str


@dataclass(frozen=True, slots=True)
class _Section:
    heading_path: tuple[str, ...]
    paragraphs: tuple[str, ...]


def _parse_sections(markdown: str) -> list[_Section]:
    sections: list[_Section] = []
    headings: list[str] = []
    paragraphs: list[str] = []
    paragraph_lines: list[str] = []
    current_path: tuple[str, ...] = ()

    def flush_paragraph() -> None:
        if paragraph_lines:
            paragraph = "\n".join(paragraph_lines).strip()
            if paragraph:
                paragraphs.append(paragraph)
            paragraph_lines.clear()

    def flush_section() -> None:
        flush_paragraph()
        if paragraphs:
            sections.append(_Section(current_path, tuple(paragraphs)))
            paragraphs.clear()

    for raw_line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading_match = _HEADING_RE.match(raw_line.strip())
        if heading_match:
            flush_section()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            headings[level - 1 :] = [title]
            current_path = tuple(headings)
        elif raw_line.strip():
            paragraph_lines.append(raw_line.strip())
        else:
            flush_paragraph()
    flush_section()
    return sections


def _split_oversized(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    sentences = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(text) if part.strip()]
    if len(sentences) == 1:
        return [text[index : index + max_chars] for index in range(0, len(text), max_chars)]

    units: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                units.append(current)
                current = ""
            units.extend(
                sentence[index : index + max_chars]
                for index in range(0, len(sentence), max_chars)
            )
        elif not current:
            current = sentence
        elif len(current) + len(sentence) <= max_chars:
            current += sentence
        else:
            units.append(current)
            current = sentence
    if current:
        units.append(current)
    return units


def _prefix_with_sentence_boundary(text: str, max_chars: int) -> str:
    """Return a non-empty prefix, preferring a sentence boundary within the limit."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return text

    prefix = text[:max_chars]
    boundaries = [match.end() for match in _SENTENCE_BOUNDARY_RE.finditer(prefix)]
    if boundaries:
        return prefix[: boundaries[-1]]
    return prefix


def _pack_section(
    paragraphs: tuple[str, ...], *, max_chars: int, overlap_chars: int, prefix_context: str = ""
) -> list[str]:
    chunks: list[str] = []
    overlap_size = min(overlap_chars, len(prefix_context))
    current = prefix_context[-overlap_size:] if overlap_size else ""
    context_only = bool(current)
    has_prefix_context = bool(current)

    def finalize_current() -> None:
        nonlocal current, context_only
        if not current:
            return
        chunks.append(current)
        overlap_size = min(overlap_chars, len(current))
        current = current[-overlap_size:] if overlap_size else ""
        context_only = bool(current)

    for paragraph_index, paragraph in enumerate(paragraphs):
        units = _split_oversized(paragraph, max_chars)
        for unit_index, unit in enumerate(units):
            pending = unit
            separator = (
                "\n\n" if unit_index == 0 and (paragraph_index > 0 or has_prefix_context) else ""
            )
            while pending:
                active_separator = separator if current else ""
                available = max_chars - len(current) - len(active_separator)

                if len(pending) <= available:
                    current += active_separator + pending
                    context_only = False
                    break

                if current and not context_only:
                    finalize_current()
                    continue

                # The context overlap is mandatory. When its separator would consume all
                # remaining space, omit that formatting separator before splitting content.
                if available <= 0 and context_only and separator:
                    separator = ""
                    continue
                if available <= 0:
                    raise ValueError("chunk capacity exhausted while preserving overlap")

                prefix = _prefix_with_sentence_boundary(pending, available)
                current += active_separator + prefix
                context_only = False
                pending = pending[len(prefix) :]
                separator = ""
                if pending:
                    finalize_current()

    if current:
        chunks.append(current)
    return chunks


def chunk_knowledge_item(
    *,
    knowledge_id: str,
    name: str,
    category: str,
    difficulty: int,
    tags: list[str],
    content_md: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[CandidateChunk]:
    if not knowledge_id.strip():
        raise ValueError("knowledge_id must be non-empty")
    if not content_md.strip():
        raise ValueError("content_md must be non-empty")
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")

    raw_chunks: list[tuple[tuple[str, ...], str]] = []
    previous_content = ""
    for section in _parse_sections(content_md):
        section_chunks = _pack_section(
            section.paragraphs,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            prefix_context=previous_content,
        )
        raw_chunks.extend((section.heading_path, content) for content in section_chunks if content)
        if section_chunks:
            previous_content = section_chunks[-1]

    chunks: list[CandidateChunk] = []
    tags_text = "、".join(tag.strip() for tag in tags if tag.strip())
    for index, (heading_path, content) in enumerate(raw_chunks):
        heading_text = " > ".join(heading_path)
        context_lines = [
            f"知识点：{name.strip()}",
            f"分类：{category.strip()}",
            f"难度：{difficulty}",
            f"标签：{tags_text}",
        ]
        if heading_text:
            context_lines.append(f"标题：{heading_text}")
        embedding_text = "\n".join([*context_lines, "", content])
        chunks.append(
            CandidateChunk(
                chunk_id=f"{knowledge_id}::chunk::{index}",
                knowledge_id=knowledge_id,
                chunk_index=index,
                heading_path=heading_path,
                content=content,
                embedding_text=embedding_text,
            )
        )
    if not chunks:
        raise ValueError("content_md produced no chunks")
    return chunks
