import re
import urllib.robotparser as robotparser
from urllib.parse import urlparse, urljoin

from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from config import USER_AGENT, RETRY_ATTEMPTS, SCROLL_PAUSE_MS, MAX_SCROLL_ATTEMPTS


def slugify(url: str) -> str:
    """Turn a URL into a filesystem-safe, human-inspectable filename."""
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "home"
    slug = re.sub(r"[^a-zA-Z0-9/_-]", "-", path)
    slug = slug.replace("/", "__")
    if parsed.query:
        slug += "__" + re.sub(r"[^a-zA-Z0-9]", "-", parsed.query)[:60]
    return slug[:200] or "home"


def is_internal(url: str, allowed_domains) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def normalize_url(base: str, link: str) -> str:
    """Resolve a relative link against base, strip fragments, normalize trailing slash."""
    url = urljoin(base, link.strip())
    parsed = urlparse(url)
    url = parsed._replace(fragment="").geturl()
    root = f"{parsed.scheme}://{parsed.netloc}/"
    if url.endswith("/") and url != root:
        url = url[:-1]
    return url


class RobotsChecker:
    def __init__(self, base_url: str):
        self.rp = robotparser.RobotFileParser()
        self.rp.set_url(urljoin(base_url, "/robots.txt"))
        try:
            self.rp.read()
        except Exception as e:
            logger.warning(f"Could not read robots.txt ({e}); defaulting to allow-all.")
            self.rp = None

    def allowed(self, url: str) -> bool:
        if self.rp is None:
            return True
        try:
            return self.rp.can_fetch(USER_AGENT, url)
        except Exception:
            return True


def retryable():
    """Standard retry policy for flaky network operations."""
    return retry(
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )


async def auto_scroll(page):
    """
    Scroll to the bottom repeatedly to trigger lazy-loaded / infinite-scroll
    content, stopping once the page height stabilizes (or after a max number
    of attempts, to guarantee termination on pages with sticky/animated footers).
    """
    last_height = 0
    stable_count = 0
    for _ in range(MAX_SCROLL_ATTEMPTS):
        height = await page.evaluate("document.body.scrollHeight")
        if height == last_height:
            stable_count += 1
            if stable_count >= 2:
                break
        else:
            stable_count = 0
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(SCROLL_PAUSE_MS)
        last_height = height
    # Scroll back to top so any "on-enter" animations don't affect final DOM oddly
    await page.evaluate("window.scrollTo(0, 0)")
