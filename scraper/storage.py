import sqlite3
import json
import threading
import datetime
from pathlib import Path
from contextlib import contextmanager


class CrawlState:
    """
    Tracks which pages/PDFs have been processed so the crawler can be killed
    and re-run without redoing work (idempotent, resumable crawl).
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                    url TEXT PRIMARY KEY,
                    status TEXT,
                    page_type TEXT,
                    error TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pdfs (
                    url TEXT PRIMARY KEY,
                    source_page TEXT,
                    local_path TEXT,
                    status TEXT,
                    error TEXT
                )
                """
            )
            conn.commit()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            yield conn
        finally:
            conn.close()

    def is_visited(self, url: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT status FROM pages WHERE url=?", (url,)).fetchone()
            return row is not None and row[0] == "done"

    def mark_page(self, url, status, page_type=None, error=None):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pages (url, status, page_type, error, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    status=excluded.status,
                    page_type=excluded.page_type,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (url, status, page_type, error, datetime.datetime.utcnow().isoformat()),
            )
            conn.commit()

    def pdf_status(self, url: str):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT status FROM pdfs WHERE url=?", (url,)).fetchone()
            return row[0] if row else None

    def mark_pdf(self, url, source_page, local_path, status, error=None):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pdfs (url, source_page, local_path, status, error)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    status=excluded.status,
                    local_path=excluded.local_path,
                    error=excluded.error
                """,
                (url, source_page, local_path, status, error),
            )
            conn.commit()

    def stats(self):
        with self._lock, self._connect() as conn:
            pages = dict(conn.execute("SELECT status, COUNT(*) FROM pages GROUP BY status").fetchall())
            pdfs = dict(conn.execute("SELECT status, COUNT(*) FROM pdfs GROUP BY status").fetchall())
            return {"pages": pages, "pdfs": pdfs}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
