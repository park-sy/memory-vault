"""web_auto_db.py — SQLite 저장소 (WAL 모드).

msgbus.py 패턴: Row factory, context manager, parameterized queries.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from web_auto_models import (
    ApprovalRequest,
    ExecutionRecord,
    now_iso,
)

logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).resolve().parent.parent / "storage"
DB_PATH = DB_DIR / "web-auto.db"

SCHEMA = """\
PRAGMA journal_mode=wal;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    flow_name TEXT NOT NULL,
    flow_type TEXT NOT NULL CHECK(flow_type IN ('read','write')),
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    input_data TEXT DEFAULT '{}',
    output_data TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    tier_used INTEGER DEFAULT 2
);

CREATE INDEX IF NOT EXISTS idx_exec_domain ON executions(domain);
CREATE INDEX IF NOT EXISTS idx_exec_status ON executions(status);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    flow_name TEXT NOT NULL,
    action_summary TEXT NOT NULL,
    input_data TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    requested_at TEXT DEFAULT (datetime('now')),
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approval_domain ON approvals(domain);

CREATE TABLE IF NOT EXISTS rate_limits (
    domain TEXT PRIMARY KEY,
    last_request_at TEXT,
    requests_today INTEGER DEFAULT 0,
    today_date TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    domain TEXT PRIMARY KEY,
    cookies TEXT DEFAULT '{}',
    local_storage TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


# ── Connection ──────────────────────────────────────────────────

@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── WebAutoDB ───────────────────────────────────────────────────

class WebAutoDB:
    """Web Automation CRUD 인터페이스."""

    # ── Executions ──────────────────────────────────────────────

    @staticmethod
    def record_execution(
        domain: str,
        flow_name: str,
        flow_type: str,
        input_data: str = "{}",
        tier_used: int = 2,
    ) -> int:
        """실행 기록 생성. 반환: execution id."""
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO executions
                   (domain, flow_name, flow_type, status, started_at, input_data, tier_used)
                   VALUES (?, ?, ?, 'running', ?, ?, ?)""",
                (domain, flow_name, flow_type, now_iso(), input_data, tier_used),
            )
            return cur.lastrowid  # type: ignore[return-value]

    @staticmethod
    def update_execution(
        exec_id: int,
        *,
        status: str | None = None,
        output_data: str | None = None,
        error: str | None = None,
    ) -> None:
        """실행 기록 업데이트."""
        # Whitelist 기반 SET clause 빌더 (SQL injection 방지)
        _ALLOWED_CLAUSES = {
            "status": "status = ?",
            "finished_at": "finished_at = ?",
            "output_data": "output_data = ?",
            "error": "error = ?",
        }
        parts: list[str] = []
        vals: list[str | int] = []
        if status is not None:
            parts.append(_ALLOWED_CLAUSES["status"])
            vals.append(status)
            if status in ("success", "failed"):
                parts.append(_ALLOWED_CLAUSES["finished_at"])
                vals.append(now_iso())
        if output_data is not None:
            parts.append(_ALLOWED_CLAUSES["output_data"])
            vals.append(output_data)
        if error is not None:
            parts.append(_ALLOWED_CLAUSES["error"])
            vals.append(error)
        if not parts:
            return
        vals.append(exec_id)
        set_clause = ", ".join(parts)
        with _connect() as conn:
            conn.execute(
                f"UPDATE executions SET {set_clause} WHERE id = ?",
                vals,
            )

    @staticmethod
    def list_executions(
        domain: str | None = None,
        limit: int = 20,
    ) -> list[ExecutionRecord]:
        """실행 이력 조회."""
        query = "SELECT * FROM executions"
        params: list[str | int] = []
        if domain:
            query += " WHERE domain = ?"
            params.append(domain)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with _connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ExecutionRecord(
                id=r["id"],
                domain=r["domain"],
                flow_name=r["flow_name"],
                flow_type=r["flow_type"],
                status=r["status"],
                started_at=r["started_at"] or "",
                finished_at=r["finished_at"] or "",
                input_data=r["input_data"] or "",
                output_data=r["output_data"] or "",
                error=r["error"] or "",
                tier_used=r["tier_used"],
            )
            for r in rows
        ]

    @staticmethod
    def has_duplicate_post(domain: str, url: str) -> bool:
        """같은 URL로 이미 성공한 write 실행이 있는지 확인."""
        # LIKE 메타문자 이스케이프 (%, _, \)
        escaped = url.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with _connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS cnt FROM executions
                   WHERE domain = ? AND flow_type = 'write'
                     AND status = 'success' AND input_data LIKE ? ESCAPE '\\'""",
                (domain, f"%{escaped}%"),
            ).fetchone()
        return (row["cnt"] if row else 0) > 0

    # ── Approvals ───────────────────────────────────────────────

    @staticmethod
    def create_approval(
        domain: str,
        flow_name: str,
        action_summary: str,
        input_data: str = "{}",
    ) -> int:
        """승인 요청 생성. 반환: approval id."""
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO approvals
                   (domain, flow_name, action_summary, input_data, status, requested_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (domain, flow_name, action_summary, input_data, now_iso()),
            )
            return cur.lastrowid  # type: ignore[return-value]

    @staticmethod
    def decide_approval(
        approval_id: int,
        approved: bool,
        reason: str = "",
    ) -> None:
        """승인/거부 결정."""
        status = "approved" if approved else "rejected"
        with _connect() as conn:
            conn.execute(
                "UPDATE approvals SET status = ?, decided_at = ? WHERE id = ?",
                (status, now_iso(), approval_id),
            )
            if reason:
                conn.execute(
                    "UPDATE approvals SET action_summary = action_summary || ? WHERE id = ?",
                    (f" [reason: {reason}]", approval_id),
                )

    @staticmethod
    def get_pending_approvals(
        domain: str | None = None,
    ) -> list[ApprovalRequest]:
        """대기 중인 승인 요청 목록."""
        query = "SELECT * FROM approvals WHERE status = 'pending'"
        params: list[str] = []
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        query += " ORDER BY id DESC"

        with _connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ApprovalRequest(
                id=r["id"],
                domain=r["domain"],
                flow_name=r["flow_name"],
                action_summary=r["action_summary"],
                input_data=r["input_data"] or "",
                status=r["status"],
                requested_at=r["requested_at"] or "",
                decided_at=r["decided_at"] or "",
            )
            for r in rows
        ]

    @staticmethod
    def get_approval(approval_id: int) -> ApprovalRequest | None:
        """단일 승인 요청 조회."""
        with _connect() as conn:
            r = conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        if not r:
            return None
        return ApprovalRequest(
            id=r["id"],
            domain=r["domain"],
            flow_name=r["flow_name"],
            action_summary=r["action_summary"],
            input_data=r["input_data"] or "",
            status=r["status"],
            requested_at=r["requested_at"] or "",
            decided_at=r["decided_at"] or "",
        )

    # ── Rate Limits ─────────────────────────────────────────────

    @staticmethod
    def check_rate_limit(domain: str, daily_cap: int) -> bool:
        """rate limit 통과 여부. True=허용."""
        today = now_iso()[:10]
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM rate_limits WHERE domain = ?", (domain,)
            ).fetchone()
        if not row:
            return True
        if row["today_date"] != today:
            return True  # 날짜 바뀜 → 리셋
        return row["requests_today"] < daily_cap

    @staticmethod
    def record_request(domain: str) -> None:
        """요청 1회 기록 (rate limit 카운트)."""
        today = now_iso()[:10]
        ts = now_iso()
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM rate_limits WHERE domain = ?", (domain,)
            ).fetchone()
            if not row:
                conn.execute(
                    """INSERT INTO rate_limits (domain, last_request_at, requests_today, today_date)
                       VALUES (?, ?, 1, ?)""",
                    (domain, ts, today),
                )
            elif row["today_date"] != today:
                conn.execute(
                    """UPDATE rate_limits
                       SET last_request_at = ?, requests_today = 1, today_date = ?
                       WHERE domain = ?""",
                    (ts, today, domain),
                )
            else:
                conn.execute(
                    """UPDATE rate_limits
                       SET last_request_at = ?, requests_today = requests_today + 1
                       WHERE domain = ?""",
                    (ts, domain),
                )

    @staticmethod
    def get_last_request_time(domain: str) -> str | None:
        """마지막 요청 시각 조회."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT last_request_at FROM rate_limits WHERE domain = ?",
                (domain,),
            ).fetchone()
        return row["last_request_at"] if row else None

    # ── Sessions ────────────────────────────────────────────────

    @staticmethod
    def save_session(domain: str, cookies: str, local_storage: str = "{}") -> None:
        """브라우저 세션 저장."""
        with _connect() as conn:
            conn.execute(
                """INSERT INTO sessions (domain, cookies, local_storage, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(domain) DO UPDATE SET
                     cookies = excluded.cookies,
                     local_storage = excluded.local_storage,
                     updated_at = excluded.updated_at""",
                (domain, cookies, local_storage, now_iso()),
            )

    @staticmethod
    def load_session(domain: str) -> dict:
        """브라우저 세션 로드. 없으면 빈 dict."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT cookies, local_storage FROM sessions WHERE domain = ?",
                (domain,),
            ).fetchone()
        if not row:
            return {"cookies": {}, "local_storage": {}}
        try:
            cookies = json.loads(row["cookies"])
        except (json.JSONDecodeError, TypeError):
            cookies = {}
        try:
            ls = json.loads(row["local_storage"])
        except (json.JSONDecodeError, TypeError):
            ls = {}
        return {"cookies": cookies, "local_storage": ls}

    # ── Stats ───────────────────────────────────────────────────

    @staticmethod
    def get_consecutive_successes(domain: str, flow_name: str) -> int:
        """최근 연속 성공 횟수 (trust level 승격 판단용)."""
        with _connect() as conn:
            rows = conn.execute(
                """SELECT status FROM executions
                   WHERE domain = ? AND flow_name = ? AND flow_type = 'write'
                   ORDER BY id DESC LIMIT 50""",
                (domain, flow_name),
            ).fetchall()
        count = 0
        for r in rows:
            if r["status"] == "success":
                count += 1
            else:
                break
        return count
