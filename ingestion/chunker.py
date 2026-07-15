"""
Turns scraped Phase-1 artifacts (data/structured/*.json, data/pdf_text/**/*.json)
into embedding-ready chunks with rich, citable metadata.
"""
import hashlib
import json
import uuid
from pathlib import Path

# Cross-sell sections repeat other pages' content verbatim and would just
# dilute a product's own chunk with unrelated products.
_CROSS_SELL_HEADINGS = {"similar products", "more from"}

_NAMESPACE = uuid.UUID("6f2f9d1e-6e7a-4b6a-9a8e-6a9f9e8b6a1a")


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_id(source_key: str, index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{source_key}::{index}"))


def split_text(text: str, size: int, overlap: int) -> list[str]:
    """Paragraph-aware greedy splitter with a char-count overlap between chunks."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        # A single paragraph longer than the target size is hard-split on its own.
        if len(para) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            start = 0
            while start < len(para):
                chunks.append(para[start:start + size])
                start += max(size - overlap, 1)
            continue

        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) > size and buf:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap else ""
            buf = f"{tail}\n\n{para}" if tail else para
        else:
            buf = candidate

    if buf:
        chunks.append(buf)
    return chunks


def _blocks_to_text(blocks: list[dict]) -> str:
    lines = []
    for b in blocks:
        text = (b.get("text") or "").strip()
        if not text:
            continue
        if b.get("type") == "list_item":
            lines.append(f"- {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines)


def _is_cross_sell_heading(text: str) -> bool:
    lowered = text.strip().lower()
    return any(lowered.startswith(h) for h in _CROSS_SELL_HEADINGS)


def chunk_structured_page(json_path: Path) -> list[dict]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    page_type = data.get("page_type", "generic")
    url = data.get("url", "")
    brand = data.get("brand")
    product_name = data.get("product_name")
    title = data.get("title")
    blocks = data.get("content_blocks", [])

    base_meta = {
        "url": url,
        "page_type": page_type,
        "brand": brand,
        "product_name": product_name,
        "title": title,
        "source": "page",
    }

    if page_type == "product":
        own_blocks = []
        for b in blocks:
            if b.get("type") == "heading" and _is_cross_sell_heading(b.get("text", "")):
                break
            own_blocks.append(b)

        text_parts = [t for t in (title,) if t]
        text_parts.append(_blocks_to_text(own_blocks))
        specs = data.get("specifications") or {}
        if specs:
            spec_lines = "\n".join(f"- {k}: {v}" for k, v in specs.items())
            text_parts.append(f"Specifications:\n{spec_lines}")
        full_text = "\n\n".join(p for p in text_parts if p).strip()
        if not full_text:
            return []

        pieces = split_text(full_text, 4000, 0) if len(full_text) > 4000 else [full_text]
        return _build_chunks(pieces, url, base_meta)

    # Non-product pages: split into heading-bounded sections (H1/H2), then
    # hard-wrap each section to the configured chunk size.
    sections: list[list[dict]] = []
    current: list[dict] = []
    for b in blocks:
        if b.get("type") == "heading" and b.get("level", 3) <= 2 and current:
            sections.append(current)
            current = [b]
        else:
            current.append(b)
    if current:
        sections.append(current)
    if not sections and blocks:
        sections = [blocks]

    from config import CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS

    all_pieces: list[str] = []
    for section in sections:
        section_text = _blocks_to_text(section)
        if not section_text:
            continue
        all_pieces.extend(split_text(section_text, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS))

    return _build_chunks(all_pieces, url, base_meta)


_MIN_CHUNK_CHARS = 30


def _build_chunks(pieces: list[str], source_key: str, base_meta: dict) -> list[dict]:
    chunks = []
    for i, piece in enumerate(pieces):
        if len(piece.strip()) < _MIN_CHUNK_CHARS:
            continue
        chunks.append({
            "chunk_id": _chunk_id(source_key, i),
            "text": piece,
            "content_hash": _content_hash(piece),
            **base_meta,
        })
    return chunks


def chunk_pdf_text(json_path: Path) -> list[dict]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not data.get("num_pages"):
        return []  # non-PDF asset (e.g. video) or extraction failed — nothing to chunk

    from config import CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS

    base_meta = {
        "url": data.get("source_page_url", ""),
        "page_type": "pdf",
        "doc_type": data.get("doc_type"),
        "brand": data.get("brand"),
        "product_name": data.get("product_name"),
        "pdf_url": data.get("pdf_url"),
        "source": "pdf",
    }

    chunks = []
    for page in data.get("pages", []):
        page_text = (page.get("text") or "").strip()
        if not page_text:
            continue
        page_number = page.get("page_number")
        source_key = f"{data.get('pdf_url', json_path.stem)}::p{page_number}"
        pieces = split_text(page_text, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS)
        meta = {**base_meta, "page_number": page_number}
        chunks.extend(_build_chunks(pieces, source_key, meta))
    return chunks
