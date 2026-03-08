"""AI Boss DB — SQLite state for tasks, feedback, checkins, config, growth metrics."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── Constants ────────────────────────────────────────────────────────────────

VAULT_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(VAULT_DIR / "storage" / "ai-boss.db")

# ── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = """\
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT DEFAULT '',
    horizon      TEXT NOT NULL CHECK(horizon IN ('daily','weekly','monthly','quarter')),
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK(status IN ('proposed','active','blocked','completed','dropped')),
    priority     INTEGER DEFAULT 5 CHECK(priority BETWEEN 1 AND 9),
    proposed_by  TEXT DEFAULT 'user',
    due_date     TEXT,
    blocked_reason TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_horizon ON tasks(horizon);

CREATE TABLE IF NOT EXISTS feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER REFERENCES tasks(id),
    boss         TEXT NOT NULL,
    content      TEXT NOT NULL,
    context      TEXT,
    checkin_type TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_feedback_boss ON feedback(boss);
CREATE INDEX IF NOT EXISTS idx_feedback_task ON feedback(task_id);

CREATE TABLE IF NOT EXISTS checkin_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    checkin_type  TEXT NOT NULL,
    bosses        TEXT NOT NULL,
    tokens_used   INTEGER DEFAULT 0,
    user_responded INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_checkin_type ON checkin_log(checkin_type);

CREATE TABLE IF NOT EXISTS boss_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS growth_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_type TEXT NOT NULL,
    value       REAL NOT NULL,
    period      TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_growth_type ON growth_metrics(metric_type);
"""

SEED_CONFIG = [
    ("morning_checkin_time", "09:00"),
    ("evening_checkin_time", "18:00"),
    ("weekly_review_day", "fri"),
    ("weekly_review_time", "17:00"),
    ("checkin_enabled", "true"),
    ("active_bosses", '["jinsu","miyoung","junghoon"]'),
]


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Task:
    id: int
    title: str
    description: str
    horizon: str
    status: str
    priority: int
    proposed_by: str
    due_date: Optional[str]
    blocked_reason: Optional[str]
    created_at: str
    completed_at: Optional[str]
    updated_at: str


@dataclass(frozen=True)
class Feedback:
    id: int
    task_id: Optional[int]
    boss: str
    content: str
    context: Optional[str]
    checkin_type: Optional[str]
    created_at: str


@dataclass(frozen=True)
class CheckinLog:
    id: int
    checkin_type: str
    bosses: str
    tokens_used: int
    user_responded: int
    created_at: str


# ── Connection ───────────────────────────────────────────────────────────────

@contextmanager
def connect(db_path: str = DB_PATH):
    """Context manager for AI Boss DB connections."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    """Create tables and seed config (idempotent)."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for key, value in SEED_CONFIG:
            conn.execute(
                """INSERT OR IGNORE INTO boss_config (key, value)
                   VALUES (?, ?)""",
                (key, value),
            )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"], title=row["title"], description=row["description"],
        horizon=row["horizon"], status=row["status"], priority=row["priority"],
        proposed_by=row["proposed_by"], due_date=row["due_date"],
        blocked_reason=row["blocked_reason"], created_at=row["created_at"],
        completed_at=row["completed_at"], updated_at=row["updated_at"],
    )


def _row_to_feedback(row: sqlite3.Row) -> Feedback:
    return Feedback(
        id=row["id"], task_id=row["task_id"], boss=row["boss"],
        content=row["content"], context=row["context"],
        checkin_type=row["checkin_type"], created_at=row["created_at"],
    )


def _row_to_checkin(row: sqlite3.Row) -> CheckinLog:
    return CheckinLog(
        id=row["id"], checkin_type=row["checkin_type"], bosses=row["bosses"],
        tokens_used=row["tokens_used"], user_responded=row["user_responded"],
        created_at=row["created_at"],
    )


# ── Config CRUD ──────────────────────────────────────────────────────────────

def get_config(key: str, db_path: str = DB_PATH) -> Optional[str]:
    """Get a config value by key."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM boss_config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_config(key: str, value: str, db_path: str = DB_PATH) -> None:
    """Upsert a config value."""
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO boss_config (key, value)
               VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = ?""",
            (key, value, value),
        )


def get_all_config(db_path: str = DB_PATH) -> dict:
    """Get all config as a dict."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM boss_config").fetchall()
        return {row["key"]: row["value"] for row in rows}


def get_active_bosses(db_path: str = DB_PATH) -> List[str]:
    """Get list of active boss names."""
    raw = get_config("active_bosses", db_path)
    if not raw:
        return ["jinsu", "miyoung", "junghoon"]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ["jinsu", "miyoung", "junghoon"]


# ── Task CRUD ────────────────────────────────────────────────────────────────

def create_task(
    title: str,
    horizon: str,
    description: str = "",
    priority: int = 5,
    proposed_by: str = "user",
    due_date: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    """Create a new task. Returns task ID."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO tasks
               (title, description, horizon, status, priority, proposed_by,
                due_date, created_at, updated_at)
               VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
            (title, description, horizon, priority, proposed_by,
             due_date, _now(), _now()),
        )
        return cur.lastrowid


def get_task(task_id: int, db_path: str = DB_PATH) -> Optional[Task]:
    """Get a task by ID."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return _row_to_task(row) if row else None


def get_active_tasks(db_path: str = DB_PATH) -> List[Task]:
    """Get all active tasks ordered by priority."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM tasks
               WHERE status IN ('active', 'blocked')
               ORDER BY priority ASC, created_at ASC"""
        ).fetchall()
        return [_row_to_task(row) for row in rows]


def get_tasks_by_horizon(
    horizon: str, db_path: str = DB_PATH,
) -> List[Task]:
    """Get active tasks for a specific horizon."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM tasks
               WHERE horizon = ? AND status IN ('active', 'blocked')
               ORDER BY priority ASC""",
            (horizon,),
        ).fetchall()
        return [_row_to_task(row) for row in rows]


def update_task_status(
    task_id: int, status: str, db_path: str = DB_PATH,
) -> None:
    """Update task status."""
    with connect(db_path) as conn:
        params = [status, _now(), task_id]
        if status == "completed":
            conn.execute(
                """UPDATE tasks SET status = ?, completed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (status, _now(), _now(), task_id),
            )
        else:
            conn.execute(
                """UPDATE tasks SET status = ?, updated_at = ?
                   WHERE id = ?""",
                (status, _now(), task_id),
            )


def block_task(
    task_id: int, reason: str, db_path: str = DB_PATH,
) -> None:
    """Mark a task as blocked with a reason."""
    with connect(db_path) as conn:
        conn.execute(
            """UPDATE tasks SET status = 'blocked', blocked_reason = ?, updated_at = ?
               WHERE id = ?""",
            (reason, _now(), task_id),
        )


# ── Feedback CRUD ────────────────────────────────────────────────────────────

def add_feedback(
    boss: str,
    content: str,
    task_id: Optional[int] = None,
    context: Optional[str] = None,
    checkin_type: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    """Record boss feedback. Returns feedback ID."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO feedback
               (task_id, boss, content, context, checkin_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (task_id, boss, content, context, checkin_type, _now()),
        )
        return cur.lastrowid


def get_recent_feedback(
    limit: int = 10, db_path: str = DB_PATH,
) -> List[Feedback]:
    """Get most recent feedback."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_feedback(row) for row in rows]


def get_feedback_by_boss(
    boss: str, limit: int = 10, db_path: str = DB_PATH,
) -> List[Feedback]:
    """Get recent feedback from a specific boss."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM feedback WHERE boss = ? ORDER BY created_at DESC LIMIT ?",
            (boss, limit),
        ).fetchall()
        return [_row_to_feedback(row) for row in rows]


# ── Checkin Log CRUD ─────────────────────────────────────────────────────────

def log_checkin(
    checkin_type: str,
    bosses: List[str],
    tokens_used: int = 0,
    db_path: str = DB_PATH,
) -> int:
    """Record a checkin event. Returns log ID."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO checkin_log
               (checkin_type, bosses, tokens_used, created_at)
               VALUES (?, ?, ?, ?)""",
            (checkin_type, json.dumps(bosses), tokens_used, _now()),
        )
        return cur.lastrowid


def mark_user_responded(
    checkin_id: int, db_path: str = DB_PATH,
) -> None:
    """Mark that user responded to a checkin."""
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE checkin_log SET user_responded = 1 WHERE id = ?",
            (checkin_id,),
        )


def get_recent_checkins(
    limit: int = 10, db_path: str = DB_PATH,
) -> List[CheckinLog]:
    """Get recent checkin logs."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM checkin_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_checkin(row) for row in rows]


def count_unresponded_checkins(
    limit: int = 5, db_path: str = DB_PATH,
) -> int:
    """Count consecutive unresponded checkins (for auto frequency reduction)."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT user_responded FROM checkin_log
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        count = 0
        for row in rows:
            if row["user_responded"] == 0:
                count += 1
            else:
                break
        return count


# ── Growth Metrics ───────────────────────────────────────────────────────────

def record_metric(
    metric_type: str,
    value: float,
    period: str,
    detail: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    """Record a growth metric. Returns metric ID."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO growth_metrics
               (metric_type, value, period, detail, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (metric_type, value, period, detail, _now()),
        )
        return cur.lastrowid


def get_metrics_by_type(
    metric_type: str, limit: int = 30, db_path: str = DB_PATH,
) -> List[dict]:
    """Get recent metrics of a specific type."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT value, period, detail, created_at
               FROM growth_metrics
               WHERE metric_type = ?
               ORDER BY created_at DESC LIMIT ?""",
            (metric_type, limit),
        ).fetchall()
        return [
            {
                "value": row["value"],
                "period": row["period"],
                "detail": row["detail"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


# ── Statistics ───────────────────────────────────────────────────────────────

def get_task_stats(db_path: str = DB_PATH) -> dict:
    """Get task completion stats."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT status, COUNT(*) as cnt
               FROM tasks
               GROUP BY status"""
        ).fetchall()
        stats = {row["status"]: row["cnt"] for row in rows}

        # By horizon
        horizon_rows = conn.execute(
            """SELECT horizon, status, COUNT(*) as cnt
               FROM tasks
               GROUP BY horizon, status"""
        ).fetchall()
        by_horizon = {}
        for row in horizon_rows:
            h = row["horizon"]
            if h not in by_horizon:
                by_horizon[h] = {}
            by_horizon[h][row["status"]] = row["cnt"]

        return {"by_status": stats, "by_horizon": by_horizon}


def get_checkin_stats(db_path: str = DB_PATH) -> dict:
    """Get checkin response stats."""
    with connect(db_path) as conn:
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(user_responded) as responded,
                SUM(tokens_used) as total_tokens
               FROM checkin_log"""
        ).fetchone()
        total = row["total"] or 0
        responded = row["responded"] or 0
        return {
            "total_checkins": total,
            "responded": responded,
            "response_rate": responded / total if total > 0 else 0.0,
            "total_tokens": row["total_tokens"] or 0,
        }
