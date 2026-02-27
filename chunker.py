import re
import tiktoken

ENCODING = tiktoken.get_encoding("cl100k_base")
TARGET_TOKENS = 400
OVERLAP_TOKENS = 80  # ~20% of target


def count_tokens(text: str) -> int:
    return len(ENCODING.encode(text))


def chunk_text(text: str) -> list[dict]:
    """
    Recursive + Sliding Window chunking.
    Splits by paragraphs first, then sentences for large paragraphs.
    Adds ~20% token overlap between consecutive chunks.
    Returns list of dicts: {chunk_index, content, token_count}
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    raw_chunks = []
    current_parts = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = count_tokens(para)

        if para_tokens > TARGET_TOKENS:
            # Flush current buffer first
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

    # Apply sliding window overlap
    result = []
    for i, chunk in enumerate(raw_chunks):
        if i > 0:
            prev_tokens = ENCODING.encode(raw_chunks[i - 1])
            overlap = ENCODING.decode(prev_tokens[-OVERLAP_TOKENS:])
            chunk = overlap + " " + chunk

        chunk = chunk.strip()
        result.append({
            "chunk_index": i,
            "content": chunk,
            "token_count": count_tokens(chunk),
        })

    return result


def _split_by_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = []
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
