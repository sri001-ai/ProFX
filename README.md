# PRO FX Agentic RAG Bot

An agentic RAG system for **profx.com** (multi-brand AV/home-automation
dealer), built with LangGraph + local Ollama models.

**This build covers Phase 1: the scraper/ingestion pipeline.** Phases 2
(vector ingestion) and 3 (LangGraph agents) are scoped in
`ingestion/README.md` and `agents/README.md` and are the next steps once
you've reviewed the scraped data.

## What Phase 1 does

Crawls `profx.com` end-to-end using a real headless browser (Playwright),
so JS-rendered content and lazy-loaded product grids are captured, not just
static HTML. For every page it:

1. Classifies the page type (`product`, `brand_hub`, `listing`, `article`,
   `contact`, `store_locator`, `generic`).
2. Extracts structured, hierarchy-preserving content — headings, paragraphs,
   and list items in document order (`content_blocks`), plus card/grid
   layouts (brand cards, category cards, blog cards) as structured
   `{title, url, description}` items (`cards`) — not one flattened text blob.
3. Finds every linked document (owner's manuals, spec sheets, brochures,
   install guides) — including ones that **aren't plain `*.pdf` URLs at
   all**: this site's CMS (admin.profx.com) stores document references as
   bare UUIDs embedded in JSON payloads (e.g.
   `"owners_manual_file":"c389c12d-..."`), only resolved to a real URL
   client-side when a user opens the relevant accordion. The extractor
   parses these directly out of the page's embedded JSON. Downloads each
   one and extracts its text page-by-page — **with OCR fallback** for
   scanned pages (rasterize page → Tesseract), and with the real file type
   detected from the HTTP response (since these UUID URLs carry no
   extension to go on).
4. Records full provenance on everything: which page a document was linked
   from, which brand/product it belongs to, inferred document type.
5. Writes a clean **Markdown file per page** (`data/markdown/`) — the
   primary "extracted text, properly structured" artifact for ingestion —
   mirroring the site's own URL path structure, alongside the raw HTML and
   structured JSON.
6. Checkpoints progress in SQLite so a killed/interrupted crawl resumes
   without redoing work.

## Project layout

```
profx-agentic-rag/
├── config.py              # all tunables in one place
├── run_scrape.py          # CLI entrypoint
├── scraper/
│   ├── crawler.py         # Playwright BFS crawler (asyncio.Queue based)
│   ├── extractors.py      # HTML → structured record (content_blocks, cards, specs, docs)
│   ├── markdown_writer.py # structured record → clean .md file
│   ├── pdf_handler.py     # document download + text extraction + OCR fallback
│   ├── storage.py         # SQLite checkpointing + JSON save helper
│   └── utils.py           # robots.txt, URL normalization, auto-scroll, retry
├── ingestion/README.md    # Phase 2 plan (Qdrant + Ollama embeddings)
├── agents/README.md       # Phase 3 plan (LangGraph multi-agent graph)
└── data/
    ├── raw_html/           # full HTML snapshot per page (debug/audit; can disable, see below)
    ├── markdown/           # clean structured .md per page, mirrors site URL structure — PRIMARY ingestion artifact
    ├── structured/         # extracted JSON, one file per page, by page_type/
    ├── pdfs/                # downloaded document binaries, by brand/product/
    ├── pdf_text/            # extracted/OCR'd document text as JSON, by brand/product/
    ├── logs/                # rotating crawl logs
    └── crawl_state.sqlite3  # resumability checkpoint DB
```

## Setup (macOS, Apple Silicon)

```bash
# 1. System dependencies for OCR
brew install tesseract poppler

# 2. Python environment
cd profx-agentic-rag
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Playwright's bundled Chromium
playwright install chromium
```

## Running it

```bash
# Smoke test first — crawl just 15 pages, sanity-check the output structure
python run_scrape.py --max-pages 15

# Inspect data/structured/ and data/pdf_text/ to confirm quality, then:

# Full crawl (safe to Ctrl+C and re-run — it resumes from crawl_state.sqlite3)
python run_scrape.py

# Or scope it to specific brand hubs:
python run_scrape.py --seed https://profx.com/kef/ https://profx.com/denon/
```

Progress prints live via a progress bar; detailed logs go to
`data/logs/crawl_*.log`.

### Tuning politeness/speed
In `config.py` (or via env vars):
- `PROFX_MAX_CONCURRENT_PAGES` (default 5) — concurrent browser tabs
- `PROFX_MAX_CONCURRENT_DOWNLOADS` (default 6) — concurrent PDF downloads
- `PROFX_REQUEST_DELAY` (default 0.5s) — delay per worker between page loads
- `PROFX_SAVE_RAW_HTML` (default true) — set to `false` to skip saving raw
  HTML snapshots once you trust extraction quality (saves disk at scale;
  the raw HTML has been the single most useful debugging tool so far, so
  keep it on until you're confident)

Your M5 Pro can comfortably push these higher (8–10 concurrent tabs), but
I've defaulted conservatively to be polite to profx.com's server — raise
them once you've confirmed the site handles it well.

## Design decisions worth knowing about

- **Playwright over requests/Scrapy alone**: you confirmed lazy-loading is a
  concern, so every page load runs an `auto_scroll()` pass that scrolls to
  bottom repeatedly until height stabilizes, guaranteeing lazy content
  renders before extraction.
- **asyncio.Queue with `.join()`**, not a naive shared-deque loop: this
  avoids a real race condition where workers can see an empty queue and
  exit while a sibling worker is about to discover new links from a page
  it's mid-processing.
- **SQLite checkpointing**: re-running `run_scrape.py` after an interrupted
  crawl will skip every page/PDF already marked `done` — no wasted re-work,
  no duplicate PDF downloads.
- **OCR fallback logic**: for each PDF page, if the embedded text is under
  `OCR_MIN_TEXT_CHARS_PER_PAGE` (40 chars — catches image-only/scanned
  pages), the page is rasterized at 300 DPI and OCR'd with Tesseract, and
  the OCR text is used if it's more substantial than what was embedded.
  This means a manual with 8 real pages and 2 scanned diagram pages gets
  correctly handled page-by-page rather than all-or-nothing.
- **Every structured record retains `url`, `brand`, `product_name` (where
  applicable)** so Phase 2 ingestion can embed with metadata for accurate
  citations ("According to the KEF R3 Meta spec sheet...") instead of
  anonymous chunks.

## What I verified before handing this to you

I ran the extractor against representative sample HTML (product page with
breadcrumbs, spec table, and PDF links) and the PDF pipeline against a
generated PDF — both produced correct structured output. I could not run
a live crawl against profx.com from this environment (network egress here
is restricted to package registries, not arbitrary websites) — that first
real run is on you, starting with `--max-pages 15` to sanity-check output
quality before committing to a full crawl.

## Next steps (Phase 2 & 3)

Once you've reviewed `data/structured/` and `data/pdf_text/` output quality:
1. I'll build the chunking + Qdrant embedding pipeline (`ingestion/`).
2. Then the LangGraph multi-agent graph (`agents/`) — router → retrieval →
   lead-capture → answer-composer — wired to your FAQ taxonomy and your
   local Ollama model.

See `ingestion/README.md` and `agents/README.md` for the detailed design
of each.
