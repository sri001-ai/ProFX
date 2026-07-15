"""Orchestrates chunk -> embed -> upsert for the whole scraped corpus."""
from pathlib import Path

from loguru import logger
from tqdm import tqdm

import config
from ingestion.chunker import chunk_structured_page, chunk_pdf_text
from ingestion.embedder import get_embedder, embed_texts
from ingestion.qdrant_store import get_client, ensure_collection, fetch_existing_hashes, upsert_chunks

EMBED_BATCH_SIZE = 32


def _collect_chunks(source: str) -> list[dict]:
    chunks: list[dict] = []

    if source in ("structured", "all"):
        files = sorted(Path(config.STRUCTURED_DIR).rglob("*.json"))
        for f in tqdm(files, desc="Chunking structured pages"):
            try:
                chunks.extend(chunk_structured_page(f))
            except Exception as e:
                logger.warning(f"Failed to chunk {f}: {e}")

    if source in ("pdf", "all"):
        files = sorted(Path(config.PDF_TEXT_DIR).rglob("*.json"))
        for f in tqdm(files, desc="Chunking PDF text"):
            try:
                chunks.extend(chunk_pdf_text(f))
            except Exception as e:
                logger.warning(f"Failed to chunk {f}: {e}")

    return chunks


def run(source: str = "all", force: bool = False, limit: int | None = None):
    chunks = _collect_chunks(source)
    logger.info(f"Collected {len(chunks)} candidate chunks from source={source}")
    if limit:
        chunks = chunks[:limit]

    if not chunks:
        logger.warning("No chunks to ingest.")
        return

    embedder = get_embedder()
    client = get_client()

    probe_vector = embed_texts(embedder, [chunks[0]["text"]])[0]
    ensure_collection(client, vector_size=len(probe_vector))

    if force:
        to_ingest = chunks
    else:
        existing = fetch_existing_hashes(client, [c["chunk_id"] for c in chunks])
        to_ingest = [c for c in chunks if existing.get(c["chunk_id"]) != c["content_hash"]]
    logger.info(f"{len(to_ingest)} chunks are new or changed (skipping {len(chunks) - len(to_ingest)} unchanged)")

    for i in tqdm(range(0, len(to_ingest), EMBED_BATCH_SIZE), desc="Embedding + upserting"):
        batch = to_ingest[i:i + EMBED_BATCH_SIZE]
        vectors = embed_texts(embedder, [c["text"] for c in batch])
        upsert_chunks(client, batch, vectors)

    count = client.count(config.QDRANT_COLLECTION).count
    logger.info(f"Done. Collection '{config.QDRANT_COLLECTION}' now has {count} points.")
