#!/usr/bin/env python3
"""
Entrypoint for Phase 1: crawl profx.com, extract structured data + PDFs.

Examples:
    # Quick smoke test — only crawl 15 pages
    python run_scrape.py --max-pages 15

    # Full crawl (resumable — safe to Ctrl+C and re-run)
    python run_scrape.py

    # Crawl starting from specific brand hubs only
    python run_scrape.py --seed https://profx.com/kef/ https://profx.com/denon/
"""
import asyncio
import argparse

from loguru import logger

from config import BASE_URL, LOG_DIR
from scraper.crawler import Crawler


def main():
    parser = argparse.ArgumentParser(description="PRO FX (profx.com) knowledge-base crawler")
    parser.add_argument("--seed", nargs="*", default=[BASE_URL], help="Seed URL(s) to start crawling from")
    parser.add_argument("--max-pages", type=int, default=None, help="Cap on pages to crawl (omit for full crawl)")
    args = parser.parse_args()

    logger.add(str(LOG_DIR / "crawl_{time}.log"), rotation="10 MB", retention="10 days")
    logger.info(f"Starting crawl. Seeds={args.seed} max_pages={args.max_pages}")

    crawler = Crawler(seed_urls=args.seed, max_pages=args.max_pages)
    asyncio.run(crawler.run())


if __name__ == "__main__":
    main()
