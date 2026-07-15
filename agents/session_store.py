"""Lightweight session registry (id/title/timestamps) for the Streamlit
sidebar. Lives in the same sqlite file as the LangGraph checkpointer but in
its own table — the checkpointer owns conversation state, this just owns the
list-of-chats view."""
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import config

_lock = threading.Lock()


def _init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT,
                last_active TEXT
            )
            """
        )
        conn.commit()


@contextmanager
def _connect():
    conn = sqlite3.connect(str(config.CHAT_STATE_DB), timeout=30)
    try:
        yield conn
    finally:
        conn.close()


def create_session() -> str:
    _init_db()
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, last_active) VALUES (?, ?, ?, ?)",
            (session_id, "New chat", now, now),
        )
        conn.commit()
    return session_id


def touch_session(session_id: str, first_message: str | None = None):
    _init_db()
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        row = conn.execute("SELECT title FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sessions (id, title, created_at, last_active) VALUES (?, ?, ?, ?)",
                (session_id, "New chat", now, now),
            )
            row = ("New chat",)

        title = row[0]
        if first_message and title == "New chat":
            title = first_message.strip()[:40] or "New chat"

        conn.execute(
            "UPDATE sessions SET title=?, last_active=? WHERE id=?",
            (title, now, session_id),
        )
        conn.commit()


def list_sessions() -> list[dict]:
    _init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, last_active FROM sessions ORDER BY last_active DESC"
        ).fetchall()
    return [{"id": r[0], "title": r[1], "created_at": r[2], "last_active": r[3]} for r in rows]


def delete_session(session_id: str, checkpointer=None):
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        conn.commit()
    if checkpointer is not None:
        checkpointer.delete_thread(session_id)
