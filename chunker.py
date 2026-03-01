import re
import tiktoken

ENCODING = tiktoken.get_encoding("cl100k_base")
TARGET_TOKENS = 400
OVERLAP_TOKENS = 80  # used only by token-based fallback

# re.MULTILINE so ^ matches start of each line, not just start of string
_HEADING_RE = re.compile(r"^(#{2,5})\s+(.+)$", re.MULTILINE)
_HEADING_LINE_RE = re.compile(r"^(#{2,5})\s+(.+)$")


def count_tokens(text: str) -> int:
    return len(ENCODING.encode(text))


def chunk_text(content: str, title: str = "") -> list[dict]:
    """
    Auto-detects structure:
    - If content has ## headings: section-based chunking with hierarchy labels.
    - Otherwise: recursive token-based chunking with sliding window overlap.

    Chunk format:
      h1 intro  →  {title}\\n\\n{body}
      h2        →  Article heading: {title}\\n\\n{h2}\\n\\n{body}
      h3        →  Article heading: {title}\\n\\n[Subsection: {h2}]\\n\\n{h3}\\n\\n{body}
      h4        →  Article heading: {title}\\n\\n[Subsection: {h3}]\\n\\n{h4}\\n\\n{body}
    """
    if _HEADING_RE.search(content):
        return _chunk_by_sections(content, title)
    return _chunk_by_tokens(content, title)


# ---------------------------------------------------------------------------
# Section-based chunking
# ---------------------------------------------------------------------------

def _chunk_by_sections(content: str, title: str = "") -> list[dict]:
    lines = content.split("\n")

    sections: list[tuple[int, str, list[str]]] = []
    intro_body: list[str] = []
    current_level: int = 0
    current_heading: str | None = None
    current_body: list[str] = []

    for line in lines:
        m = _HEADING_LINE_RE.match(line.strip())
        if m:
            if current_heading is None:
                intro_body = [l for l in current_body if l]
            else:
                sections.append((current_level, current_heading, [l for l in current_body if l]))
            current_level = len(m.group(1))
            current_heading = m.group(2).strip()
            current_body = []
        else:
            stripped = line.strip()
            if stripped:
                current_body.append(stripped)

    if current_heading is not None:
        sections.append((current_level, current_heading, [l for l in current_body if l]))

    chunks: list[dict] = []

    # Intro paragraphs (before first heading): h1 + body, no "Article heading:" label
    if intro_body:
        body_text = "\n\n".join(intro_body)
        intro_content = f"{title}\n\n{body_text}" if title else body_text
        chunks.append(_make_chunk(len(chunks), intro_content))

    # heading_stack tracks the most recent heading at each level
    heading_stack: dict[int, str] = {}

    for level, heading, body in sections:
        heading_stack[level] = heading
        # Clear deeper levels when stepping back up
        for l in list(heading_stack.keys()):
            if l > level:
                del heading_stack[l]

        # Direct parent = closest level strictly above current
        parent: str | None = None
        for l in sorted(heading_stack.keys(), reverse=True):
            if l < level:
                parent = heading_stack[l]
                break

        body_text = "\n\n".join(body)

        def build_parts(body_segment: str) -> list[str]:
            parts = []
            if title:
                parts.append(f"Article heading: {title}")
            if parent:
                parts.append(f"Subsection: {parent}")
            parts.append(heading)
            if body_segment:
                parts.append(body_segment)
            return parts

        if body_text and count_tokens(body_text) > TARGET_TOKENS:
            for sub in _split_by_sentences(body_text):
                chunks.append(_make_chunk(len(chunks), "\n\n".join(build_parts(sub))))
        else:
            chunks.append(_make_chunk(len(chunks), "\n\n".join(build_parts(body_text))))

    return chunks


def _make_chunk(index: int, content: str) -> dict:
    content = content.strip()
    return {"chunk_index": index, "content": content, "token_count": count_tokens(content)}


# ---------------------------------------------------------------------------
# Token-based chunking (fallback for unstructured content)
# ---------------------------------------------------------------------------

def _chunk_by_tokens(content: str, title: str = "") -> list[dict]:
    """
    Recursive paragraph + sentence chunking with sliding window overlap.
    Used when content has no heading structure.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]

    raw_chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = count_tokens(para)

        if para_tokens > TARGET_TOKENS:
            if current_parts:
                raw_chunks.append(" ".join(current_parts))
                current_parts = []
                current_tokens = 0
            raw_chunks.extend(_split_by_sentences(para))
        elif current_tokens + para_tokens > TARGET_TOKENS:
            raw_chunks.append(" ".join(current_parts))
            current_parts = [para]
            current_tokens = para_tokens
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        raw_chunks.append(" ".join(current_parts))

    result: list[dict] = []
    for i, chunk in enumerate(raw_chunks):
        if i > 0:
            prev_tokens = ENCODING.encode(raw_chunks[i - 1])
            overlap = ENCODING.decode(prev_tokens[-OVERLAP_TOKENS:])
            chunk = overlap + " " + chunk
        if title:
            chunk = f"Article heading: {title}\n\n{chunk}"
        result.append(_make_chunk(i, chunk))

    return result


def _split_by_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sent in sentences:
        sent_tokens = count_tokens(sent)
        if current_tokens + sent_tokens > TARGET_TOKENS and current:
            chunks.append(" ".join(current))
            current = [sent]
            current_tokens = sent_tokens
        else:
            current.append(sent)
            current_tokens += sent_tokens

    if current:
        chunks.append(" ".join(current))

    return chunks
