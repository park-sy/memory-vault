"""Feature Factory DB — SQLite state for worker assignments, approvals, events."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .config import FACTORY_DB_PATH, DEFAULT_SUPERVISION

# ── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = """\
CREATE TABLE IF NOT EXISTS worker_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'assigned'
        CHECK(status IN ('assigned','completed','failed','timed_out')),
    assigned_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_wa_status ON worker_assignments(status);
CREATE INDEX IF NOT EXISTS idx_wa_worker ON worker_assignments(worker_id, status);
CREATE INDEX IF NOT EXISTS idx_wa_task ON worker_assignments(task_id, status);

CREATE TABLE IF NOT EXISTS factory_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS factory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fe_task ON factory_events(task_id);
CREATE INDEX IF NOT EXISTS idx_fe_type ON factory_events(event_type);

CREATE TABLE IF NOT EXISTS pending_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    gate_type TEXT NOT NULL,
    msgbus_msg_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','approved','rejected','timed_out')),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT
);

CREATE INDEX IF NOT EXISTS idx_pa_status ON pending_approvals(status);
CREATE INDEX IF NOT EXISTS idx_pa_msgbus ON pending_approvals(msgbus_msg_id);
"""

SEED_CONFIG = [
    ("supervision", DEFAULT_SUPERVISION),
    ("paused", "false"),
    ("base_pool_size", "1"),
    ("max_pool_size", "3"),
    ("idle_timeout", "600"),
    ("stall_timeout", "900"),
    ("approval_timeout", "1800"),
    ("max_concurrent_features", "3"),
]


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WorkerAssignment:
    id: int
    worker_id: int
    task_id: int
    role: str
    stage: str
    status: str
    assigned_at: str
    completed_at: Optional[str]


@dataclass(frozen=True)
class PendingApproval:
    id: int
    task_id: int
    gate_type: str
    msgbus_msg_id: int
    status: str
    created_at: str
    resolved_at: Optional[str]
    resolution: Optional[str]


@dataclass(frozen=True)
class FactoryEvent:
    id: int
    task_id: int
    event_type: str
    detail: Optional[str]
    created_at: str


# ── Connection ───────────────────────────────────────────────────────────────

@contextmanager
def connect(db_path: str = FACTORY_DB_PATH):
    """Context manager for factory DB connections."""
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


def init_db(db_path: str = FACTORY_DB_PATH) -> None:
    """Create tables and seed config (idempotent)."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for key, value in SEED_CONFIG:
            conn.execute(
                """INSERT OR IGNORE INTO factory_config (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (key, value, _now()),
            )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_assignment(row: sqlite3.Row) -> WorkerAssignment:
    return WorkerAssignment(
        id=row["id"], worker_id=row["worker_id"], task_id=row["task_id"],
        role=row["role"], stage=row["stage"], status=row["status"],
        assigned_at=row["assigned_at"], completed_at=row["completed_at"],
    )


def _row_to_approval(row: sqlite3.Row) -> PendingApproval:
    return PendingApproval(
        id=row["id"], task_id=row["task_id"], gate_type=row["gate_type"],
        msgbus_msg_id=row["msgbus_msg_id"], status=row["status"],
        created_at=row["created_at"], resolved_at=row["resolved_at"],
        resolution=row["resolution"],
    )


def _row_to_event(row: sqlite3.Row) -> FactoryEvent:
    return FactoryEvent(
        id=row["id"], task_id=row["task_id"], event_type=row["event_type"],
        detail=row["detail"], created_at=row["created_at"],
    )


# ── Config CRUD ──────────────────────────────────────────────────────────────

def get_config(key: str, db_path: str = FACTORY_DB_PATH) -> Optional[str]:
    """Get a config value by key."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM factory_config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_config(key: str, value: str, db_path: str = FACTORY_DB_PATH) -> None:
    """Upsert a config value."""
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO factory_config (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
            (key, value, _now(), value, _now()),
        )


def get_all_config(db_path: str = FACTORY_DB_PATH) -> dict:
    """Get all config as a dict."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM factory_config").fetchall()
        return {row["key"]: row["value"] for row in rows}


# ── Worker Assignment CRUD ───────────────────────────────────────────────────

def create_assignment(
    worker_id: int, task_id: int, role: str, stage: str,
    db_path: str = FACTORY_DB_PATH,
) -> int:
    """Create a new worker assignment. Returns assignment ID."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO worker_assignments
               (worker_id, task_id, role, stage, status, assigned_at)
               VALUES (?, ?, ?, ?, 'assigned', ?)""",
            (worker_id, task_id, role, stage, _now()),
        )
        return cur.lastrowid


def complete_assignment(
    assignment_id: int, status: str = "completed",
    db_path: str = FACTORY_DB_PATH,
) -> None:
    """Mark an assignment as completed/failed/timed_out."""
    with connect(db_path) as conn:
        conn.execute(
            """UPDATE worker_assignments
               SET status = ?, completed_at = ?
               WHERE id = ?""",
            (status, _now(), assignment_id),
        )


def get_active_assignment_for_task(
    task_id: int, db_path: str = FACTORY_DB_PATH,
) -> Optional[WorkerAssignment]:
    """Get the current active assignment for a task."""
    with connect(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM worker_assignments
               WHERE task_id = ? AND status = 'assigned'
               ORDER BY assigned_at DESC LIMIT 1""",
            (task_id,),
        ).fetchone()
        return _row_to_assignment(row) if row else None


def get_active_assignment_for_worker(
    worker_id: int, db_path: str = FACTORY_DB_PATH,
) -> Optional[WorkerAssignment]:
    """Get the current active assignment for a worker."""
    with connect(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM worker_assignments
               WHERE worker_id = ? AND status = 'assigned'
               ORDER BY assigned_at DESC LIMIT 1""",
            (worker_id,),
        ).fetchone()
        return _row_to_assignment(row) if row else None


def get_assigned_worker_ids(db_path: str = FACTORY_DB_PATH) -> List[int]:
    """Get all worker IDs with active assignments."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT worker_id FROM worker_assignments WHERE status = 'assigned'"
        ).fetchall()
        return [row["worker_id"] for row in rows]


# ── Pending Approvals CRUD ───────────────────────────────────────────────────

def create_approval(
    task_id: int, gate_type: str, msgbus_msg_id: int,
    db_path: str = FACTORY_DB_PATH,
) -> int:
    """Create a pending approval request. Returns approval ID."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO pending_approvals
               (task_id, gate_type, msgbus_msg_id, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (task_id, gate_type, msgbus_msg_id, _now()),
        )
        return cur.lastrowid


def resolve_approval(
    approval_id: int, resolution: str,
    db_path: str = FACTORY_DB_PATH,
) -> None:
    """Resolve a pending approval (approved/rejected)."""
    with connect(db_path) as conn:
        conn.execute(
            """UPDATE pending_approvals
               SET status = ?, resolved_at = ?, resolution = ?
               WHERE id = ?""",
            (resolution, _now(), resolution, approval_id),
        )


def find_approval_by_msgbus_id(
    msgbus_msg_id: int, db_path: str = FACTORY_DB_PATH,
) -> Optional[PendingApproval]:
    """Find a pending approval by its MsgBus message ID."""
    with connect(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM pending_approvals
               WHERE msgbus_msg_id = ? AND status = 'pending'""",
            (msgbus_msg_id,),
        ).fetchone()
        return _row_to_approval(row) if row else None


def get_pending_approvals(db_path: str = FACTORY_DB_PATH) -> List[PendingApproval]:
    """Get all pending approval requests."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM pending_approvals WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return [_row_to_approval(row) for row in rows]


def get_timed_out_approvals(
    timeout_seconds: int, db_path: str = FACTORY_DB_PATH,
) -> List[PendingApproval]:
    """Get approvals that exceeded the timeout."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM pending_approvals
               WHERE status = 'pending'
               AND julianday('now') - julianday(created_at) > ? / 86400.0""",
            (timeout_seconds,),
        ).fetchall()
        return [_row_to_approval(row) for row in rows]


# ── Event Log ────────────────────────────────────────────────────────────────

def log_event(
    task_id: int, event_type: str, detail: Optional[dict] = None,
    db_path: str = FACTORY_DB_PATH,
) -> int:
    """Log a factory event. Returns event ID."""
    detail_str = json.dumps(detail, ensure_ascii=False) if detail else None
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO factory_events (task_id, event_type, detail, created_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, event_type, detail_str, _now()),
        )
        return cur.lastrowid


def get_events_for_task(
    task_id: int, db_path: str = FACTORY_DB_PATH,
) -> List[FactoryEvent]:
    """Get all events for a specific task."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM factory_events WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [_row_to_event(row) for row in rows]


def get_recent_events(
    limit: int = 20, db_path: str = FACTORY_DB_PATH,
) -> List[FactoryEvent]:
    """Get most recent events across all tasks."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM factory_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_event(row) for row in rows]
