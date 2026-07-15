"""
Turns raw HTML into structured records. This is where "understanding" of the
PRO FX site's layout lives: page classification, spec extraction, PDF-link
discovery with doc-type inference, breadcrumb/brand detection, etc.

IMPORTANT: profx.com is a Next.js (App Router / RSC) site, NOT WordPress/
WooCommerce. There is no classic breadcrumb nav or spec-table markup to lean
on structurally. What IS reliable:
  - Brand hub pages live at /brands/<slug> (not /<slug>/).
  - Pages that represent an actual product embed schema.org JSON-LD
    (<script type="application/ld+json"> with @type "Product"), which gives
    us brand, name, description, sku, price, images directly — far more
    reliable than guessing from CSS classes on a Next.js/Tailwind site where
    class names are largely non-semantic utility classes.
  - BreadcrumbList JSON-LD, when present, is a reliable breadcrumb source.

So classification/extraction here is JSON-LD-first, with DOM-based fallbacks
for pages that don't have structured data (about, contact, solutions, blog).
"""
import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from scraper.utils import normalize_url, is_internal

# Brand slugs as they appear in /brands/<slug> URLs on profx.com (confirmed
# from the site's footer/mega-menu). Update this list if new brands are added.
KNOWN_BRANDS = [
    "kef", "denon", "polk", "theory", "prism", "fx", "definitive-technology",
    "hegel", "jbl", "revel", "chord-company", "sonodyne", "peavey",
    "crest-audio", "nakymatone",
]

PRODUCT_URL_HINTS = ["/product/", "/products/", "/shop/"]

DOC_KEYWORDS = {
    "owner": "owners_manual",
    "manual": "owners_manual",
    "spec": "spec_sheet",
    "datasheet": "spec_sheet",
    "data sheet": "spec_sheet",
    "brochure": "brochure",
    "catalogue": "catalogue",
    "catalog": "catalogue",
    "install": "installation_guide",
    "warranty": "warranty",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ---------------------------------------------------------------------------
# JSON-LD (schema.org) extraction — the primary structured-data source on
# this Next.js site.
# ---------------------------------------------------------------------------

def extract_json_ld(soup) -> list:
    """Parse every <script type="application/ld+json"> block on the page.
    Returns a flat list of dicts (handles both single-object and @graph/array
    forms)."""
    blocks = []
    for tag in soup.select('script[type="application/ld+json"]'):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, list):
            blocks.extend(b for b in data if isinstance(b, dict))
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                blocks.extend(b for b in data["@graph"] if isinstance(b, dict))
            else:
                blocks.append(data)
    return blocks


def _find_ld_type(blocks, type_name):
    for b in blocks:
        t = b.get("@type")
        if t == type_name or (isinstance(t, list) and type_name in t):
            return b
    return None


def classify_page_type(url: str, soup: BeautifulSoup, ld_blocks=None, html: str = "") -> str:
    path = urlparse(url.lower()).path
    ld_blocks = ld_blocks if ld_blocks is not None else extract_json_ld(soup)

    if _find_ld_type(ld_blocks, "Product"):
        return "product"

    # Strong product signal specific to this site: the "Details & Specifications"
    # accordion embeds *_file UUID keys (owners_manual_file, information_sheet_file,
    # etc.) only on genuine product detail pages.
    if html and ASSET_FILE_KEY_RE.search(html):
        return "product"

    if any(h in path for h in PRODUCT_URL_HINTS):
        return "product"
    # Fallback CSS-based product signals (in case some product template does
    # render classic markup even without JSON-LD)
    if soup.select_one("table.specifications, .spec-table, .product-specs, [itemtype*='schema.org/Product']"):
        return "product"

    segs = [s for s in path.split("/") if s]
    brand_slugs = set(KNOWN_BRANDS)
    if len(segs) == 2 and segs[0] == "brands" and segs[1] in brand_slugs:
        return "brand_hub"
    if segs and segs[0] == "brands" and len(segs) > 2:
        # deeper brand pages (category/series listing) that aren't a single
        # product per the checks above
        return "listing"

    if segs and segs[0] == "category":
        return "listing"
    if segs and segs[0] == "solutions":
        return "solution"
    if "contact" in path:
        return "contact"
    if "store-locator" in path or "showroom" in path or "store-service-locator" in path:
        return "store_locator"
    if "/blogs" in path or "/news" in path or "/press" in path:
        return "article"
    if "/faqs" in path:
        return "faq"

    return "generic"


def extract_breadcrumbs(soup, ld_blocks=None):
    ld_blocks = ld_blocks if ld_blocks is not None else extract_json_ld(soup)
    bc_ld = _find_ld_type(ld_blocks, "BreadcrumbList")
    if bc_ld and bc_ld.get("itemListElement"):
        items = sorted(bc_ld["itemListElement"], key=lambda i: i.get("position", 0))
        names = [_clean(i.get("name", "")) for i in items if i.get("name")]
        if names:
            return names

    # DOM fallback for pages without BreadcrumbList JSON-LD
    crumbs = []
    nav = soup.select_one("nav.breadcrumb, .breadcrumbs, .breadcrumb, [class*='breadcrumb']")
    if nav:
        for a in nav.select("a, span"):
            t = _clean(a.get_text())
            if t and t not in crumbs:
                crumbs.append(t)
    return crumbs


def extract_brand(url: str, breadcrumbs, product_ld=None):
    if product_ld:
        brand = product_ld.get("brand")
        if isinstance(brand, dict) and brand.get("name"):
            return _clean(brand["name"])
        if isinstance(brand, str) and brand.strip():
            return _clean(brand)

    path = urlparse(url.lower()).path
    segs = [s for s in path.split("/") if s]
    if len(segs) >= 2 and segs[0] == "brands" and segs[1] in KNOWN_BRANDS:
        return segs[1].replace("-", " ").title()

    for c in breadcrumbs:
        for b in KNOWN_BRANDS:
            if b.replace("-", " ").lower() == c.lower():
                return b.replace("-", " ").title()
    return None


def extract_specifications(soup, product_ld=None, embedded_price=None) -> dict:
    """Prefer JSON-LD Product fields (sku, price, description-derived specs);
    fall back to any <table>/<dl> key-value markup present on the page, and
    finally to the price recovered from the embedded RSC JSON payload (see
    extract_embedded_product_price) for pages where no JSON-LD Product/offers
    block is present at all (confirmed real case: /brands/denon/avc-a1-h has
    only a WebSite ld+json block, no Product — schema.org alone loses the
    price entirely on such pages)."""
    specs = {}

    if product_ld:
        if product_ld.get("sku"):
            specs["SKU"] = _clean(str(product_ld["sku"]))
        if product_ld.get("mpn"):
            specs["Model Number"] = _clean(str(product_ld["mpn"]))
        offers = product_ld.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        if isinstance(offers, dict) and offers.get("price"):
            currency = offers.get("priceCurrency", "")
            specs["Price"] = _clean(f"{offers['price']} {currency}".strip())
        # additionalProperty is the standard schema.org place for spec key/values
        for prop in product_ld.get("additionalProperty", []) or []:
            if isinstance(prop, dict) and prop.get("name") and prop.get("value"):
                specs[_clean(str(prop["name"]))] = _clean(str(prop["value"]))

    for table in soup.select("table"):
        for row in table.select("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) == 2:
                key, val = _clean(cells[0].get_text()), _clean(cells[1].get_text())
                if key and val:
                    specs.setdefault(key, val)
    for dl in soup.select("dl"):
        keys = [_clean(dt.get_text()) for dt in dl.select("dt")]
        vals = [_clean(dd.get_text()) for dd in dl.select("dd")]
        for k, v in zip(keys, vals):
            if k and v:
                specs.setdefault(k, v)

    if embedded_price is not None:
        specs.setdefault("Price", f"MRP ₹ {_format_inr(embedded_price)}")

    return specs


def _format_inr(amount: int) -> str:
    """Format an integer using Indian digit grouping (lakhs/crores), matching
    how the site itself displays MRP (e.g. 899900 -> '8,99,900')."""
    s = str(int(amount))
    if len(s) <= 3:
        return s
    last3, rest = s[-3:], s[:-3]
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return ",".join(parts) + "," + last3


# ---------------------------------------------------------------------------
# Embedded RSC-payload product data. This site's Product pages don't always
# emit a schema.org JSON-LD "Product"/"offers" block (confirmed: the Denon
# AVC-A1H page's only ld+json block is @type "WebSite") — so price can't be
# assumed to come from JSON-LD at all on this site, contrary to this file's
# original JSON-LD-first design. The real source of truth is the product-card
# JSON embedded in the Next.js RSC stream (self.__next_f.push(...)), which
# consistently emits slug/title/sub_title/price/short_description together
# for EVERY product card referenced on a page — including the page's own
# product AND any "Similar Products" cards sitting right next to it in the
# same payload. Matching strictly by slug (from the page URL) is required:
# grabbing the first "price" in the payload picks up an unrelated product's
# price (confirmed real case: the AVC-A1H page's raw HTML also contains a
# "price":679900 entry, but that belongs to a different, similarly-named
# product, "Denon AVC-A10H" — not this page's product, whose own price is
# "price":899900, matching the visible "MRP ₹ 8,99,900" on the page).
# ---------------------------------------------------------------------------
EMBEDDED_PRODUCT_RE = re.compile(
    r'\\?"slug\\?"\s*:\s*\\?"([^"\\]+)\\?"'
    r'\s*,\s*\\?"title\\?"\s*:\s*\\?"([^"\\]*)\\?"'
    r'\s*,\s*\\?"sub_title\\?"\s*:\s*(?:\\?"[^"\\]*\\?"|null)'
    r'\s*,\s*\\?"price\\?"\s*:\s*(\d+)'
)


def extract_embedded_product_price(html: str, url: str):
    """Find the current page's own price in the embedded RSC product-card
    JSON, matched by URL slug (not just the first price found on the page —
    see module docstring above for why that would be wrong)."""
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1] if path else ""
    if not slug:
        return None
    for m in EMBEDDED_PRODUCT_RE.finditer(html):
        if m.group(1) == slug:
            return int(m.group(3))
    return None


PDF_URL_ABS_RE = re.compile(r'https?://[^\s"\'<>\\]+\.pdf(?:\?[^\s"\'<>\\]*)?', re.IGNORECASE)
PDF_URL_REL_RE = re.compile(r'(?<!http:)(?<!https:)(?<![\w./])(/[^\s"\'<>\\]+\.pdf(?:\?[^\s"\'<>\\]*)?)', re.IGNORECASE)

# This site's CMS (admin.profx.com, Directus-style headless backend) stores
# document references as BARE UUIDs inside its JSON payload — not as URLs,
# and not in the DOM at all. The frontend only builds the real
# https://admin.profx.com/assets/<uuid> URL client-side when a user opens
# the relevant accordion/dropdown. Confirmed pattern from a real product
# page: "owners_manual_file":"c389c12d-89d1-4141-883f-028c93dca0f2". Because
# this JSON is itself embedded as a STRING inside Next.js's RSC payload, the
# quotes are backslash-escaped in the raw HTML (\"key\":\"value\"), so the
# regex tolerates an optional backslash before each quote.
ASSET_FILE_KEY_RE = re.compile(
    r'\\?"([a-zA-Z0-9_]*_file)\\?"\s*:\s*\\?"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\\?"'
)
ASSET_BASE_URL = "https://admin.profx.com/assets/"


def extract_embedded_asset_docs(html: str) -> list:
    """Find document references embedded as bare UUIDs in the page's JSON
    payload (see ASSET_FILE_KEY_RE docstring above) and resolve them to
    real, downloadable asset URLs. The JSON key itself doubles as a
    surprisingly good label — e.g. "owners_manual_file" -> "Owners Manual",
    "information_sheet_file" -> "Information Sheet" — so no separate label
    lookup is needed."""
    docs, seen = [], set()
    for key, uuid in ASSET_FILE_KEY_RE.findall(html):
        url = ASSET_BASE_URL + uuid
        if url in seen:
            continue
        seen.add(url)
        label = key[:-5].replace("_", " ").title() if key.endswith("_file") else key.replace("_", " ").title()
        docs.append({"url": url, "label": label, "doc_type": _infer_doc_type(label)})
    return docs


def _infer_doc_type(text_and_url: str) -> str:
    low = text_and_url.lower()
    for kw, dt in DOC_KEYWORDS.items():
        if kw in low:
            return dt
    return "document"


# CMS asset links (admin.profx.com/assets/<uuid>) never carry a file
# extension, so a suffix check can't identify them by URL shape alone. This
# pattern matches the *host+shape* of such links regardless of extension.
CMS_ASSET_HREF_RE = re.compile(
    r'^https?://admin\.profx\.com/assets/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?:\?.*)?$',
    re.IGNORECASE,
)
DOC_ICON_HINTS = ("pdf", "document", "doc-icon", "file-icon")


def _anchor_has_doc_icon(a) -> bool:
    """True if the anchor visually presents as a document download — e.g.
    contains a /pdf.svg icon, the exact pattern confirmed from the site's
    real markup (a document-icon <img> + title + download-arrow <svg>)."""
    for img in a.find_all("img"):
        src = (img.get("src") or img.get("data-src") or "").lower()
        if any(h in src for h in DOC_ICON_HINTS):
            return True
    return False


def extract_pdf_links(soup, html, page_url):
    """Find every document reference on the page. Three passes, because
    this site references documents in ways a plain `<a href="*.pdf">` scan
    would miss entirely:

      1. Classic DOM anchors: <a href="...pdf">Label</a>.
      2. CMS asset-link anchors: <a href="https://admin.profx.com/assets/
         <uuid>"> with NO file extension — identified either by a document
         icon inside the anchor (confirmed real pattern: an <img src="/pdf.svg">
         alongside the title) or by the URL matching the CMS's UUID-asset
         shape. This is the case confirmed directly from a live screenshot
         of an "Owners Manual" download button on this site.
      3. Regex over the FULL raw HTML/JSON text for any *.pdf-looking URL,
         catching PDFs referenced inside Next.js RSC JSON payloads or
         non-anchor patterns (onClick handlers, data-* attributes, etc.)

    Deduplicated by resolved absolute URL.
    """
    links = []
    seen = set()

    for a in soup.select("a[href]"):
        href = a["href"]
        full = urljoin(page_url, href)
        label = _clean(a.get_text())

        if href.lower().split("?")[0].endswith(".pdf"):
            links.append({"url": full, "label": label, "doc_type": _infer_doc_type(label + " " + href)})
            seen.add(full)
        elif full not in seen and (CMS_ASSET_HREF_RE.match(full) or _anchor_has_doc_icon(a)):
            links.append({"url": full, "label": label, "doc_type": _infer_doc_type(label + " " + href)})
            seen.add(full)

    for m in PDF_URL_ABS_RE.findall(html):
        if m not in seen:
            links.append({"url": m, "label": "", "doc_type": _infer_doc_type(m)})
            seen.add(m)

    for m in PDF_URL_REL_RE.findall(html):
        full = urljoin(page_url, m)
        if full not in seen:
            links.append({"url": full, "label": "", "doc_type": _infer_doc_type(m)})
            seen.add(full)

    return links


def extract_meta_description(soup) -> str:
    tag = soup.select_one('meta[name="description"], meta[property="og:description"]')
    return _clean(tag["content"]) if tag and tag.get("content") else ""


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def extract_content_blocks(soup) -> list:
    """Walk the <main> region in document order and produce structured
    blocks (heading/paragraph/list_item) instead of one flattened text
    string. This preserves section hierarchy and reading order, which
    matters a lot for chunking quality downstream — a flat text blob loses
    which paragraph belongs under which heading."""
    soup = BeautifulSoup(str(soup), "lxml")  # work on a copy
    for tag in soup.select("script, style, nav, header, footer, .cookie-banner"):
        tag.decompose()
    main = soup.select_one("main") or soup.body
    if not main:
        return []

    blocks = []
    seen_texts = set()  # collapse Next.js hydration duplicates (same text rendered twice)
    for el in main.find_all(list(HEADING_TAGS) + ["p", "li"]):
        text = _clean(el.get_text(" "))
        if not text or len(text) < 2:
            continue
        if text in seen_texts:
            continue
        seen_texts.add(text)

        if el.name in HEADING_TAGS:
            blocks.append({"type": "heading", "level": int(el.name[1]), "text": text})
        elif el.name == "li":
            blocks.append({"type": "list_item", "text": text})
        else:
            blocks.append({"type": "paragraph", "text": text})

    return blocks[:500]


def blocks_to_text(blocks: list) -> str:
    """Flatten content_blocks back into readable text, for full-text search
    or as a convenience field — headings get a blank line before them so
    section boundaries are still visible."""
    lines = []
    for b in blocks:
        if b["type"] == "heading":
            lines.append("")
            lines.append(b["text"])
        elif b["type"] == "list_item":
            lines.append(f"- {b['text']}")
        else:
            lines.append(b["text"])
    return "\n".join(lines).strip()[:20000]


def extract_cards(soup, page_url, allowed_domains) -> list:
    """Extract repeated grid/card layouts (brand cards, category cards, blog
    post cards, solution cards) as structured {title, url, description}
    items instead of losing them in a flattened text blob.

    Two card layouts show up on this site:
      1. Heading nested directly inside the <a> (brand/category cards).
      2. Heading as a SIBLING of the link within a shared card wrapper —
         image-link + separate title + "Read More" link (blog cards).

    So for each heading, we first check if it's inside a link; if not, we
    walk up a few ancestor levels looking for the nearest container that
    holds an internal link — that's the card's URL."""
    main = soup.select_one("main") or soup.body
    if not main:
        return []

    cards, seen = [], set()
    for h in main.find_all(HEADING_TAGS):
        title = _clean(h.get_text())
        if not title:
            continue

        link = h.find_parent("a", href=True)
        container = h.parent
        depth = 0
        while link is None and container is not None and container.name not in ("main", "body") and depth < 2:
            a = container.find("a", href=True)
            if a:
                link = a
            container = container.parent
            depth += 1

        if link is None:
            continue
        href = normalize_url(page_url, link["href"])
        if not is_internal(href, allowed_domains):
            continue
        key = (title, href)
        if key in seen:
            continue
        seen.add(key)

        # best-effort short description + image: look within a few ancestor
        # levels of the heading for the first <p> / <img> that isn't the
        # heading itself
        desc, image_url = "", None
        node, d = h.parent, 0
        while node is not None and node.name not in ("main", "body") and d < 4:
            if not desc:
                p = node.find("p")
                if p:
                    desc = _clean(p.get_text())
            if image_url is None:
                img = node.find("img")
                if img:
                    src = img.get("data-src") or img.get("src")
                    if src and not src.startswith("data:"):
                        image_url = urljoin(page_url, src)
            if desc and image_url:
                break
            node = node.parent
            d += 1

        cards.append({"title": title, "url": href, "description": desc, "image": image_url})

    # Drop cases where 2+ distinct headings resolved to the same href — that's
    # a shared CTA/container link (e.g. one "Explore Products" button sitting
    # near several unrelated headings in the same section), not a genuine
    # one-card-per-link grid item.
    from collections import Counter
    href_counts = Counter(c["url"] for c in cards)
    cards = [c for c in cards if href_counts[c["url"]] == 1]

    return cards[:150]


def extract_images(soup, page_url):
    imgs = []
    for img in soup.select("img[src], img[data-src], img[srcset]"):
        src = img.get("data-src") or img.get("src")
        if src and not src.startswith("data:"):
            imgs.append(urljoin(page_url, src))
    return list(dict.fromkeys(imgs))[:30]


def extract_internal_links(soup, page_url, allowed_domains):
    links = []
    for a in soup.select("a[href]"):
        href = a["href"]
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = normalize_url(page_url, href)
        if is_internal(full, allowed_domains) and not full.lower().split("?")[0].endswith(".pdf"):
            links.append(full)
    return list(dict.fromkeys(links))


def extract_page_title(soup):
    if soup.title and soup.title.string:
        return _clean(soup.title.string)
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        return _clean(og["content"])
    h1 = soup.select_one("h1")
    return _clean(h1.get_text()) if h1 else ""


def extract_product_name(soup, title, product_ld=None):
    if product_ld and product_ld.get("name"):
        return _clean(product_ld["name"])
    h1 = soup.select_one("h1")
    return _clean(h1.get_text()) if h1 else title


def extract_page(url: str, html: str, allowed_domains) -> dict:
    """Main entrypoint: HTML string -> structured record dict."""
    soup = BeautifulSoup(html, "lxml")
    ld_blocks = extract_json_ld(soup)
    product_ld = _find_ld_type(ld_blocks, "Product")

    page_type = classify_page_type(url, soup, ld_blocks, html)
    breadcrumbs = extract_breadcrumbs(soup, ld_blocks)
    title = extract_page_title(soup)
    content_blocks = extract_content_blocks(soup)
    cards = extract_cards(soup, url, allowed_domains)

    pdf_links = extract_pdf_links(soup, html, url)
    seen_urls = {d["url"] for d in pdf_links}
    for d in extract_embedded_asset_docs(html):
        if d["url"] not in seen_urls:
            pdf_links.append(d)
            seen_urls.add(d["url"])

    # A card whose link IS a document (e.g. a "View Owner's Manual" button
    # that happens to wrap a heading) isn't a navigational card — it's
    # already captured above, so drop it here to avoid double-representing it.
    cards = [c for c in cards if c["url"] not in seen_urls]

    record = {
        "url": url,
        "page_type": page_type,
        "title": title,
        "meta_description": extract_meta_description(soup),
        "breadcrumbs": breadcrumbs,
        "brand": extract_brand(url, breadcrumbs, product_ld),
        "content_blocks": content_blocks,     # structured, hierarchy-preserving
        "text": blocks_to_text(content_blocks),  # flattened convenience field
        "cards": cards,                         # structured card/grid items (brands, categories, blog posts, ...)
        "images": extract_images(soup, url),
        "pdf_links": pdf_links,
        "internal_links": extract_internal_links(soup, url, allowed_domains),
    }

    if page_type == "product":
        embedded_price = extract_embedded_product_price(html, url)
        record["product_name"] = extract_product_name(soup, title, product_ld)
        record["specifications"] = extract_specifications(soup, product_ld, embedded_price)
        if product_ld and product_ld.get("description") and not record["meta_description"]:
            record["meta_description"] = _clean(str(product_ld["description"]))

    return record
