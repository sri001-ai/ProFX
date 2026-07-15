"""
Downloads every document linked from a scraped page (owner's manuals, spec
sheets, brochures, install guides) and extracts their text. Pages with
little/no embedded text (i.e. scanned images) are rasterized and OCR'd with
Tesseract.

IMPORTANT: on this site, document URLs are often extension-less headless-CMS
asset endpoints (e.g. https://admin.profx.com/assets/<uuid>) rather than
plain *.pdf links — the URL itself gives no hint about file type. So instead
of trusting the URL, we download first and detect the real file type from
the HTTP response's Content-Type header, then only run PDF text/OCR
extraction if it's actually a PDF.

Every extracted record retains full provenance: which page it was found on,
the brand/product it belongs to, and the inferred document type — so the
ingestion stage can attach correct metadata/citations later.
"""
import asyncio
import io
import mimetypes
from pathlib import Path

import httpx
import fitz  # PyMuPDF
from loguru import logger

from config import (
    PDF_DIR, PDF_TEXT_DIR, MAX_CONCURRENT_DOWNLOADS,
    OCR_MIN_TEXT_CHARS_PER_PAGE, OCR_DPI,
)
from scraper.storage import save_json
from scraper.utils import slugify, retryable

_download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


def _guess_filename(url: str) -> str:
    """Best-effort filename from the URL. For UUID-style asset endpoints
    with no extension, this just returns the UUID — the real extension gets
    appended after we see the Content-Type header in _download()."""
    return url.rstrip("/").split("/")[-1].split("?")[0] or "document"


@retryable()
async def _download(client: httpx.AsyncClient, url: str, dest_dir: Path, base_name: str):
    """Download a file, determining its real extension from the response's
    Content-Type header (needed for extension-less CMS asset URLs). Returns
    (final_path, content_type)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    async with client.stream("GET", url, timeout=60) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()

        if "." in base_name:
            final_name = base_name
        else:
            ext = ".pdf" if content_type == "application/pdf" else (mimetypes.guess_extension(content_type) or ".bin")
            final_name = base_name + ext

        dest = dest_dir / final_name
        with open(dest, "wb") as f:
            async for chunk in resp.aiter_bytes():
                f.write(chunk)
    return dest, content_type


def _ocr_page(page) -> str:
    """Rasterize a PDF page and OCR it with Tesseract. Requires the
    `tesseract` binary to be installed on the system (brew install tesseract)."""
    import pytesseract
    from PIL import Image, ImageOps

    pix = page.get_pixmap(dpi=OCR_DPI)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    img = ImageOps.autocontrast(img)  # light preprocessing improves OCR accuracy
    return pytesseract.image_to_string(img)


def extract_pdf_text(pdf_path: Path) -> dict:
    """Extract text per page. Falls back to OCR for pages whose embedded
    text is suspiciously short (scanned manuals, image-only spec sheets)."""
    doc = fitz.open(pdf_path)
    pages, ocr_used = [], False
    for i, page in enumerate(doc):
        text = page.get_text("text")
        if len(text.strip()) < OCR_MIN_TEXT_CHARS_PER_PAGE:
            try:
                ocr_text = _ocr_page(page)
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
                    ocr_used = True
            except Exception as e:
                logger.warning(f"OCR failed on {pdf_path.name} page {i + 1}: {e}")
        pages.append({"page_number": i + 1, "text": text.strip()})
    doc.close()
    return {"pages": pages, "ocr_used": ocr_used, "num_pages": len(pages)}


async def process_pdf(client, doc_url, source_page_url, brand, product_name, doc_type, state):
    """Download (if needed) + extract a single document, recording
    provenance. Handles both classic *.pdf URLs and extension-less CMS
    asset URLs — the real type is determined from the HTTP response, not
    guessed from the URL."""
    if state.pdf_status(doc_url) == "done":
        return

    async with _download_semaphore:
        base_name = _guess_filename(doc_url)
        subdir = f"{slugify(brand or 'misc')}/{slugify(product_name or 'general')}"
        dest_dir = PDF_DIR / subdir
        # find any existing local file for this url (by base_name, any extension)
        existing = list(dest_dir.glob(base_name + ".*")) if dest_dir.exists() else []

        try:
            if existing:
                dest = existing[0]
                content_type = "application/pdf" if dest.suffix.lower() == ".pdf" else mimetypes.guess_type(str(dest))[0] or ""
            else:
                dest, content_type = await _download(client, doc_url, dest_dir, base_name)

            is_pdf = content_type == "application/pdf" or dest.suffix.lower() == ".pdf"

            if is_pdf:
                extracted = await asyncio.to_thread(extract_pdf_text, dest)
            else:
                extracted = {
                    "pages": [], "ocr_used": False, "num_pages": 0,
                    "note": f"Downloaded but content-type was '{content_type or 'unknown'}', not a PDF — skipped text/OCR extraction.",
                }

            record = {
                "pdf_url": doc_url,
                "local_path": str(dest),
                "content_type": content_type,
                "source_page_url": source_page_url,
                "brand": brand,
                "product_name": product_name,
                "doc_type": doc_type,
                **extracted,
            }
            out_path = PDF_TEXT_DIR / subdir / (dest.stem + ".json")
            save_json(out_path, record)
            state.mark_pdf(doc_url, source_page_url, str(dest), "done")
            logger.info(
                f"Document done: {doc_url} -> {dest.name} "
                f"(type={content_type}, pages={extracted.get('num_pages', 0)}, ocr_used={extracted.get('ocr_used', False)})"
            )
        except Exception as e:
            logger.error(f"Document failed: {doc_url} -> {e}")
            state.mark_pdf(doc_url, source_page_url, str(dest_dir / base_name), "error", str(e))
