# Phase 2 — Ingestion (not yet built; this is the plan)

Once `data/structured/*.json` and `data/pdf_text/**/*.json` are populated by the
scraper, this stage will:

1. **Chunk** each source:
   - Product pages → one chunk per product (name + brand + description + full
     spec table serialized as text), small enough to stay coherent, tagged
     with `page_type`, `brand`, `url`, `product_name`.
   - PDF text → chunked per logical section (fallback: per page), tagged with
     `source_page_url`, `brand`, `product_name`, `doc_type`, `pdf_url`,
     `page_number` — so the bot can cite "see page 4 of the KEF R3 Meta
     owner's manual" with a working link.
   - Generic/brand-hub/listing pages → chunked by heading sections.

2. **Embed** each chunk with an Ollama embedding model (`nomic-embed-text`,
   configured in `config.py` as `OLLAMA_EMBED_MODEL`) via the local Ollama
   server (`http://localhost:11434`).

3. **Upsert into Qdrant** (`config.QDRANT_URL`, collection
   `profx_knowledge_base`), storing the full metadata payload alongside each
   vector so retrieval results carry brand/URL/doc-type context directly —
   no second lookup needed.

4. Support **incremental re-ingestion**: re-running only re-embeds
   chunks whose source content hash changed since the last run (content hash
   stored in the Qdrant payload).

## Setup for this phase (when we build it)
```bash
docker run -p 6333:6333 -v $(pwd)/qdrant_storage:/qdrant/storage qdrant/qdrant
ollama pull nomic-embed-text
```
