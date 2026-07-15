"""
Renders a structured page record (from scraper.extractors.extract_page) into
a clean, readable Markdown document — this is the primary "extracted text,
properly structured" artifact for ingestion, sitting alongside the raw HTML
and JSON.

Files are written mirroring the site's own URL path structure (the same
structure the sitemap itself encodes), not flat slugs, so the on-disk layout
matches the site's information architecture and is easy to browse by hand:

    https://profx.com/brands/kef/r-series/r3-meta
      -> data/markdown/brands/kef/r-series/r3-meta.md

    https://profx.com/ (root)
      -> data/markdown/index.md
"""
from pathlib import Path
from urllib.parse import urlparse


def url_to_relative_path(url: str, suffix: str = ".md") -> Path:
    """Map a URL to a relative file path mirroring its path segments."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return Path("index" + suffix)
    parts = [p for p in path.split("/") if p]
    *subdirs, filename = parts
    return Path(*subdirs, filename + suffix)


def _spec_table(specs: dict) -> list:
    if not specs:
        return []
    lines = ["| Field | Value |", "|---|---|"]
    for k, v in specs.items():
        k_clean = str(k).replace("|", "/").strip()
        v_clean = str(v).replace("|", "/").replace("\n", " ").strip()
        if k_clean:
            lines.append(f"| {k_clean} | {v_clean} |")
    return lines


def render_markdown(record: dict) -> str:
    """Build a Markdown document from a structured page record. Content
    hierarchy (headings/paragraphs/lists) is preserved in document order;
    specs render as a table; cards and documents render as linked lists —
    all of it kept in clearly labeled sections so chunking and metadata
    extraction downstream have clean boundaries to work with."""
    lines = []

    title = record.get("product_name") or record.get("title") or record["url"]
    lines.append(f"# {title}")
    lines.append("")

    # --- Front-matter-ish metadata block ---
    lines.append(f"- **URL:** {record['url']}")
    lines.append(f"- **Page type:** {record['page_type']}")
    if record.get("brand"):
        lines.append(f"- **Brand:** {record['brand']}")
    if record.get("breadcrumbs"):
        lines.append(f"- **Breadcrumbs:** {' > '.join(record['breadcrumbs'])}")
    lines.append("")

    if record.get("meta_description"):
        lines.append(f"> {record['meta_description']}")
        lines.append("")

    # --- Specifications (product pages) ---
    specs = record.get("specifications")
    if specs:
        lines.append("## Specifications")
        lines.append("")
        lines.extend(_spec_table(specs))
        lines.append("")

    # --- Main content, hierarchy-preserving ---
    blocks = record.get("content_blocks") or []
    if blocks:
        lines.append("## Content")
        lines.append("")
        for b in blocks:
            if b["type"] == "heading":
                # offset so page-level headings never collide with the H1 title above
                level = min(b.get("level", 2) + 1, 6)
                lines.append(f"{'#' * level} {b['text']}")
                lines.append("")
            elif b["type"] == "list_item":
                lines.append(f"- {b['text']}")
            else:
                lines.append(b["text"])
                lines.append("")

    # --- Related items (brand cards, category cards, blog cards, etc.) ---
    cards = record.get("cards") or []
    if cards:
        lines.append("## Related items")
        lines.append("")
        for c in cards:
            desc = f" — {c['description']}" if c.get("description") else ""
            lines.append(f"- [{c['title']}]({c['url']}){desc}")
        lines.append("")

    # --- Documents (manuals, spec sheets, brochures) ---
    docs = record.get("pdf_links") or []
    if docs:
        lines.append("## Documents")
        lines.append("")
        for d in docs:
            label = d.get("label") or d.get("doc_type", "Document")
            lines.append(f"- **{label}** ({d.get('doc_type', 'document')}): {d['url']}")
        lines.append("")

    if record.get("images"):
        lines.append(f"*({len(record['images'])} image(s) on this page — see structured JSON for URLs)*")
        lines.append("")

    return "\n".join(lines).strip() + "\n"
