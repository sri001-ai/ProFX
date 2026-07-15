"""
Async, resumable, polite crawler for profx.com.

Design notes:
- Uses Playwright (full Chromium) so JS-rendered / lazy-loaded content
  (product grids, "load more" sections, animated reveals) is captured, not
  just the static HTML.
- Uses an asyncio.Queue (producer/consumer with .join()) rather than a naive
  "while queue: pop" loop across workers — that pattern race-conditions when
  multiple workers discover new links concurrently and the queue empties
  mid-flight. Queue.join() correctly waits for ALL in-flight + newly
  discovered work before terminating.
- Every page and PDF is checkpointed in SQLite (scraper/storage.py), so a
  killed/interrupted run can simply be re-launched and will skip completed
  work.
- Respects robots.txt and applies a per-worker delay to avoid hammering
  the site.
"""
import asyncio

import httpx
from loguru import logger
from playwright.async_api import async_playwright
from tqdm import tqdm

from config import (
    BASE_URL, ALLOWED_DOMAINS, RAW_HTML_DIR, MARKDOWN_DIR, STRUCTURED_DIR, STATE_DB,
    MAX_CONCURRENT_PAGES, NAV_TIMEOUT_MS, USER_AGENT, REQUEST_DELAY_SECONDS, SAVE_RAW_HTML,
)
from scraper.storage import CrawlState, save_json
from scraper.extractors import extract_page
from scraper.markdown_writer import render_markdown, url_to_relative_path
from scraper.pdf_handler import process_pdf
from scraper.utils import auto_scroll, normalize_url, is_internal, slugify, RobotsChecker, retryable


class Crawler:
    def __init__(self, seed_urls=None, max_pages=None):
        self.seed_urls = seed_urls or [BASE_URL]
        self.max_pages = max_pages
        self.state = CrawlState(STATE_DB)
        self.robots = RobotsChecker(BASE_URL)

        self.queue: asyncio.Queue = asyncio.Queue()
        self.queued = set()
        for u in self.seed_urls:
            self.queue.put_nowait(u)
            self.queued.add(u)

        self.sem = asyncio.Semaphore(MAX_CONCURRENT_PAGES)
        self.pages_done = 0
        self.pdf_tasks = []
        self.http_client = None
        self.pbar = None

    async def _fetch_sitemap(self):
        """Seed the queue from sitemap.xml if available — much faster/more
        complete discovery than pure link-following alone."""
        try:
            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=20) as c:
                r = await c.get(normalize_url(BASE_URL, "/sitemap.xml"))
                if r.status_code == 200 and "xml" in r.headers.get("content-type", ""):
                    import re
                    urls = re.findall(r"<loc>(.*?)</loc>", r.text)
                    added = 0
                    for u in urls:
                        if u.lower().endswith(".xml"):
                            continue  # a sitemap index; nested-index fetching is a TODO if needed
                        if is_internal(u, ALLOWED_DOMAINS) and u not in self.queued:
                            self.queue.put_nowait(u)
                            self.queued.add(u)
                            added += 1
                    logger.info(f"Sitemap seeded {added} URLs")
        except Exception as e:
            logger.warning(f"Sitemap fetch failed (continuing with link-crawl only): {e}")

    @retryable()
    async def _load_page(self, context, url):
        page = await context.new_page()
        try:
            await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(500)
            await auto_scroll(page)  # trigger lazy-loaded content
            return await page.content()
        finally:
            await page.close()

    async def _process_url(self, context, url):
        if self.state.is_visited(url):
            return
        if not self.robots.allowed(url):
            self.state.mark_page(url, "skipped_robots")
            return
        if self.max_pages and self.pages_done >= self.max_pages:
            return

        async with self.sem:
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
            try:
                html = await self._load_page(context, url)
            except Exception as e:
                logger.error(f"Failed to load {url}: {e}")
                self.state.mark_page(url, "error", error=str(e))
                return

        if SAVE_RAW_HTML:
            (RAW_HTML_DIR / (slugify(url) + ".html")).write_text(html, encoding="utf-8")

        try:
            record = extract_page(url, html, ALLOWED_DOMAINS)
        except Exception as e:
            logger.error(f"Extraction failed for {url}: {e}")
            self.state.mark_page(url, "error", error=str(e))
            return

        out_path = STRUCTURED_DIR / record["page_type"] / (slugify(url) + ".json")
        save_json(out_path, record)

        md_path = MARKDOWN_DIR / url_to_relative_path(url)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_markdown(record), encoding="utf-8")

        self.state.mark_page(url, "done", page_type=record["page_type"])
        self.pages_done += 1
        if self.pbar is not None:
            # NOTE: never use truthy `if self.pbar:` — tqdm overrides __bool__ and
            # raises TypeError when total/iterable are both None (our case, since
            # crawl size isn't known upfront). Always use `is not None`.
            self.pbar.update(1)
            self.pbar.set_postfix_str(record["page_type"])

        for link in record["internal_links"]:
            if link not in self.queued and not self.state.is_visited(link):
                self.queued.add(link)
                await self.queue.put(link)

        for pdf in record["pdf_links"]:
            self.pdf_tasks.append(
                process_pdf(
                    self.http_client, pdf["url"], url,
                    record.get("brand"), record.get("product_name") or record.get("title"),
                    pdf["doc_type"], self.state,
                )
            )

    async def _worker(self, context):
        while True:
            url = await self.queue.get()
            try:
                await self._process_url(context, url)
            except Exception as e:
                logger.exception(f"Unhandled worker error on {url}: {e}")
            finally:
                self.queue.task_done()

    async def run(self):
        await self._fetch_sitemap()

        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as http_client:
            self.http_client = http_client

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(user_agent=USER_AGENT)

                self.pbar = tqdm(desc="Crawling", unit="page")
                workers = [asyncio.create_task(self._worker(context)) for _ in range(MAX_CONCURRENT_PAGES)]

                await self.queue.join()  # waits until ALL discovered work (including work
                                          # discovered mid-crawl) has been processed

                for w in workers:
                    w.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                self.pbar.close()
                await browser.close()

            logger.info(f"Downloading & extracting {len(self.pdf_tasks)} PDFs...")
            for i in range(0, len(self.pdf_tasks), 20):
                await asyncio.gather(*self.pdf_tasks[i:i + 20])

        stats = self.state.stats()
        logger.info(f"Crawl complete. Pages: {self.pages_done}. State: {stats}")
