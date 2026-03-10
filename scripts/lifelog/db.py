"""Lifelog DB — SQLite storage for life log entries."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── Constants ────────────────────────────────────────────────────────────────

VAULT_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(VAULT_DIR / "storage" / "lifelog.db")

# ── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = """\
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    categories TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    sentiment TEXT DEFAULT 'neutral',
    metadata TEXT DEFAULT '{}',
    classified INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at);
CREATE INDEX IF NOT EXISTS idx_entries_source ON entries(source);
CREATE INDEX IF NOT EXISTS idx_entries_classified ON entries(classified);
"""


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Entry:
    id: int
    content: str
    source: str
    categories: List[str]
    tags: List[str]
    sentiment: str
    metadata: dict
    classified: bool
    created_at: str


# ── Connection ───────────────────────────────────────────────────────────────

@contextmanager
def connect(db_path: str = DB_PATH):
    """Context manager for lifelog DB connections."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    """Create tables (idempotent)."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"],
        content=row["content"],
        source=row["source"],
        categories=json.loads(row["categories"] or "[]"),
        tags=json.loads(row["tags"] or "[]"),
        sentiment=row["sentiment"] or "neutral",
        metadata=json.loads(row["metadata"] or "{}"),
        classified=bool(row["classified"]),
        created_at=row["created_at"],
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────

def insert_entry(
    content: str,
    source: str = "manual",
    categories: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    sentiment: str = "neutral",
    metadata: Optional[dict] = None,
    classified: bool = False,
    db_path: str = DB_PATH,
) -> int:
    """Insert a new entry. Returns entry ID."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO entries
               (content, source, categories, tags, sentiment, metadata,
                classified, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                content,
                source,
                json.dumps(categories or [], ensure_ascii=False),
                json.dumps(tags or [], ensure_ascii=False),
                sentiment,
                json.dumps(metadata or {}, ensure_ascii=False),
                1 if classified else 0,
                _now_iso(),
            ),
        )
        return cur.lastrowid


def get_unclassified(limit: int = 50, db_path: str = DB_PATH) -> List[Entry]:
    """Get unclassified entries."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM entries
               WHERE classified = 0
               ORDER BY created_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [_row_to_entry(row) for row in rows]


def update_classification(
    entry_id: int,
    categories: List[str],
    tags: List[str],
    sentiment: str,
    db_path: str = DB_PATH,
) -> None:
    """Update classification result for an entry."""
    with connect(db_path) as conn:
        conn.execute(
            """UPDATE entries
               SET categories = ?, tags = ?, sentiment = ?, classified = 1
               WHERE id = ?""",
            (
                json.dumps(categories, ensure_ascii=False),
                json.dumps(tags, ensure_ascii=False),
                sentiment,
                entry_id,
            ),
        )


def get_entries(
    since: Optional[str] = None,
    categories: Optional[List[str]] = None,
    source: Optional[str] = None,
    limit: int = 100,
    db_path: str = DB_PATH,
) -> List[Entry]:
    """Query entries with filters.

    Args:
        since: ISO8601 timestamp or relative like "24h", "7d".
        categories: Filter entries containing ANY of these categories.
        source: Filter by source type.
        limit: Max results.
    """
    conditions = []
    params: list = []

    if since:
        since_ts = _resolve_since(since)
        conditions.append("created_at >= ?")
        params.append(since_ts)

    if source:
        conditions.append("source = ?")
        params.append(source)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    with connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT * FROM entries
                {where}
                ORDER BY created_at DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()

        entries = [_row_to_entry(row) for row in rows]

    if categories:
        cat_set = set(categories)
        entries = [
            e for e in entries
            if cat_set.intersection(e.categories)
        ]

    return entries


def _resolve_since(since: str) -> str:
    """Convert relative time like '24h', '7d' to ISO8601 timestamp."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)

    if since.endswith("h"):
        delta = timedelta(hours=int(since[:-1]))
    elif since.endswith("d"):
        delta = timedelta(days=int(since[:-1]))
    elif since.endswith("w"):
        delta = timedelta(weeks=int(since[:-1]))
    else:
        return since  # assume already ISO8601

    target = now - delta
    return target.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_entry_count(db_path: str = DB_PATH) -> dict:
    """Get entry count stats."""
    with connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM entries").fetchone()["cnt"]
        classified = conn.execute(
            "SELECT COUNT(*) as cnt FROM entries WHERE classified = 1"
        ).fetchone()["cnt"]
        return {"total": total, "classified": classified, "unclassified": total - classified}
