#!/usr/bin/env python3
"""
Entrypoint for Phase 2: chunk scraped data, embed via Ollama, upsert into Qdrant.

Examples:
    # Full ingestion (incremental — re-running only re-embeds changed chunks)
    python run_ingest.py

    # Only re-ingest product/listing/etc. pages, not PDFs
    python run_ingest.py --source structured

    # Force full re-embed of everything, ignoring content hashes
    python run_ingest.py --force

    # Smoke test on a handful of chunks
    python run_ingest.py --limit 20
"""
import argparse

from loguru import logger

from config import LOG_DIR
from ingestion.pipeline import run


def main():
    parser = argparse.ArgumentParser(description="PRO FX knowledge-base ingestion (chunk -> embed -> Qdrant)")
    parser.add_argument("--source", choices=["structured", "pdf", "all"], default="all")
    parser.add_argument("--force", action="store_true", help="Re-embed all chunks, ignoring content hashes")
    parser.add_argument("--limit", type=int, default=None, help="Cap on number of chunks to ingest (debugging)")
    args = parser.parse_args()

    logger.add(str(LOG_DIR / "ingest_{time}.log"), rotation="10 MB", retention="10 days")
    logger.info(f"Starting ingestion. source={args.source} force={args.force} limit={args.limit}")

    run(source=args.source, force=args.force, limit=args.limit)


if __name__ == "__main__":
    main()
