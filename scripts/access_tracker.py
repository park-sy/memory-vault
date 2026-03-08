#!/usr/bin/env python3
"""PostToolUse hook — Read 도구 사용 시 memory-vault .md 파일의 접근을 SQLite에 기록.

Claude Code가 stdin으로 전달하는 JSON:
{
  "tool_name": "Read",
  "tool_input": { "file_path": "/Users/.../02-knowledge/patterns/x.md" },
  "tool_response": "..."
}

기록 대상:
- file_role_access: (file_path, role, access_count, last_accessed)
- session_role: (session_id, active_role, updated_at)

역할 감지: memory.md 읽기에서 추론 (01-org/core/{role}/memory.md → role)
세션 ID: os.getppid() (Claude Code PID, 세션 인스턴스마다 고유)

DB 경로: storage/access_tracker.db

대상 디렉토리:
- 01-org/core/*/memory.md
- 01-org/enabling/*/memory.md
- 02-knowledge/**/*.md
- 03-projects/**/*.md (overview, context, developer-memory)
- 04-decisions/**/*.md
- 05-sessions/**/*.md
- 06-skills/**/*.md
- 07-clone/**/*.md

제외:
- CLAUDE.md (진입점, frontmatter 없음)
- templates/ (템플릿은 추적 안 함)
- 00-MOC/ (MOC는 추적 안 함)
- role.md (역할 정의, frontmatter 없음)
- head.md, identity.md, user.md (SOUL 파일)

Exit 0: 정상 (block하지 않음)
"""

import json
import os
import random
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

VAULT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = VAULT_DIR / "storage" / "access_tracker.db"

# 추적 대상 디렉토리 (vault root 기준 상대 경로)
TRACKED_PREFIXES = (
    "01-org/core/",
    "01-org/enabling/",
    "02-knowledge/",
    "03-projects/",
    "04-decisions/",
    "05-sessions/",
    "06-skills/",
    "07-clone/",
)

# 추적 제외 파일 패턴
EXCLUDED_NAMES = {
    "CLAUDE.md",
    "_team.md",
}

EXCLUDED_SUFFIXES = (
    "/role.md",
    "/head.md",
    "/identity.md",
    "/user.md",
    "/orchestrator.md",
    "/developer.md",
)


def _is_tracked(file_path: Path) -> bool:
    """추적 대상 파일인지 판별."""
    if not file_path.suffix == ".md":
        return False

    try:
        rel = file_path.relative_to(VAULT_DIR)
    except ValueError:
        return False

    rel_str = str(rel)

    if file_path.name in EXCLUDED_NAMES:
        return False

    for suffix in EXCLUDED_SUFFIXES:
        if rel_str.endswith(suffix):
            return False

    if rel_str.startswith("templates/") or rel_str.startswith("00-MOC/"):
        return False

    return any(rel_str.startswith(prefix) for prefix in TRACKED_PREFIXES)


def _infer_role(rel_path: str) -> Optional[str]:
    """memory 파일 읽기에서 역할 추론. 역할 파일이 아니면 None.

    Examples:
        "01-org/core/coder/memory.md" → "coder"
        "01-org/enabling/orchestrator/memory.md" → "orchestrator"
        "03-projects/learning/specialist-memory.md" → "learning-specialist"
        "03-projects/whos-life/developer-memory.md" → "whos-life-developer"
        "02-knowledge/patterns/test.md" → None
    """
    parts = rel_path.split("/")

    # 코어팀: 01-org/core/{role}/memory.md
    if rel_path.endswith("/memory.md"):
        if rel_path.startswith("01-org/core/") and len(parts) == 4:
            return parts[2]
        if rel_path.startswith("01-org/enabling/") and len(parts) == 4:
            return parts[2]

    # 도메인팀: 03-projects/{name}/specialist-memory.md or developer-memory.md
    if rel_path.startswith("03-projects/") and len(parts) == 3:
        filename = parts[2]
        project_name = parts[1]
        if filename == "specialist-memory.md":
            return f"{project_name}-specialist"
        if filename == "developer-memory.md":
            return f"{project_name}-developer"

    return None


def _get_session_id() -> str:
    """Claude Code PID 기반 세션 ID."""
    return str(os.getppid())


def _init_db(db_path: Path) -> sqlite3.Connection:
    """DB 초기화. 테이블이 없으면 생성, 기존 file_access 테이블은 삭제."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_role_access (
            file_path     TEXT NOT NULL,
            role          TEXT NOT NULL,
            access_count  INTEGER NOT NULL DEFAULT 0,
            last_accessed TEXT NOT NULL,
            PRIMARY KEY (file_path, role)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_role (
            session_id  TEXT PRIMARY KEY,
            active_role TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    # 기존 file_access 테이블 삭제 (역할 귀속 불가 데이터)
    conn.execute("DROP TABLE IF EXISTS file_access")
    conn.commit()
    return conn


def _record_access(
    conn: sqlite3.Connection, rel_path: str, session_id: str, today: str
) -> None:
    """접근 기록. 역할 감지 → session_role 업데이트 → file_role_access 기록."""
    # 1. 역할 감지: memory.md이면 active_role 업데이트
    role = _infer_role(rel_path)
    if role:
        conn.execute("""
            INSERT INTO session_role (session_id, active_role, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                active_role = ?, updated_at = ?
        """, (session_id, role, today, role, today))

    # 2. 현재 세션의 active_role 조회
    row = conn.execute(
        "SELECT active_role FROM session_role WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    active_role = row[0] if row else None

    # 3. file_role_access 업데이트
    if active_role:
        conn.execute("""
            INSERT INTO file_role_access (file_path, role, access_count, last_accessed)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(file_path, role) DO UPDATE SET
                access_count = access_count + 1,
                last_accessed = ?
        """, (rel_path, active_role, today, today))
    else:
        # 역할 미확인 시 (세션 시작 직후, memory.md 읽기 전) → role="unknown"
        conn.execute("""
            INSERT INTO file_role_access (file_path, role, access_count, last_accessed)
            VALUES (?, 'unknown', 1, ?)
            ON CONFLICT(file_path, role) DO UPDATE SET
                access_count = access_count + 1,
                last_accessed = ?
        """, (rel_path, today, today))

    conn.commit()

    # 4. session_role 정리 (1/50 확률로 7일 이전 세션 삭제)
    if random.randint(1, 50) == 1:
        conn.execute("DELETE FROM session_role WHERE updated_at < date('now', '-7 days')")
        conn.commit()


def get_access_info(file_path: str, db_path: Optional[Path] = None) -> Tuple[Optional[str], int]:
    """파일의 접근 정보를 DB에서 조회 (역할 합산).

    Args:
        file_path: vault root 기준 상대 경로
        db_path: DB 경로 (기본값: VAULT_DIR/storage/access_tracker.db)

    Returns:
        (last_accessed, total_count) 튜플. 레코드 없으면 (None, 0).
    """
    actual_db = db_path or DB_PATH
    if not actual_db.exists():
        return (None, 0)

    conn = sqlite3.connect(str(actual_db))
    try:
        row = conn.execute(
            "SELECT MAX(last_accessed), SUM(access_count) FROM file_role_access WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        if row is None or row[1] is None:
            return (None, 0)
        return (row[0], row[1])
    finally:
        conn.close()


def get_all_access_info(db_path: Optional[Path] = None) -> dict:
    """모든 파일의 접근 정보를 DB에서 조회.

    Returns:
        {
            "02-knowledge/patterns/test.md": {
                "last_accessed": "2026-03-03",
                "total_count": 15,
                "role_counts": {"coder": 10, "planner": 5},
            }
        }
    """
    actual_db = db_path or DB_PATH
    if not actual_db.exists():
        return {}

    conn = sqlite3.connect(str(actual_db))
    try:
        rows = conn.execute(
            "SELECT file_path, role, access_count, last_accessed FROM file_role_access"
        ).fetchall()

        result = {}
        for file_path, role, count, last in rows:
            if file_path not in result:
                result[file_path] = {
                    "last_accessed": last,
                    "total_count": 0,
                    "role_counts": {},
                }
            entry = result[file_path]
            entry["total_count"] += count
            entry["role_counts"][role] = count
            # MAX(last_accessed) — 가장 최근 날짜 유지
            if last > entry["last_accessed"]:
                entry["last_accessed"] = last

        return result
    finally:
        conn.close()


def get_role_baselines(db_path: Optional[Path] = None) -> dict:
    """각 역할의 memory.md 카운트 (reference_rate 계산의 분모).

    Returns:
        {"coder": 100, "planner": 10, "orchestrator": 5}

    구현: file_role_access에서 memory.md 파일의 role별 access_count 조회.
    """
    actual_db = db_path or DB_PATH
    if not actual_db.exists():
        return {}

    conn = sqlite3.connect(str(actual_db))
    try:
        rows = conn.execute(
            "SELECT role, SUM(access_count) FROM file_role_access "
            "WHERE file_path LIKE '%/memory.md' "
            "AND (file_path LIKE '01-org/core/%' OR file_path LIKE '01-org/enabling/%') "
            "GROUP BY role"
        ).fetchall()
        return {role: count for role, count in rows}
    finally:
        conn.close()


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        payload = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return

    tool_name = payload.get("tool_name", "")
    if tool_name != "Read":
        return

    file_path_str = payload.get("tool_input", {}).get("file_path", "")
    if not file_path_str:
        return

    file_path = Path(file_path_str).resolve()

    if not _is_tracked(file_path):
        return

    if not file_path.exists():
        return

    try:
        rel_path = str(file_path.relative_to(VAULT_DIR))
    except ValueError:
        return

    today = date.today().isoformat()
    session_id = _get_session_id()

    try:
        conn = _init_db(DB_PATH)
        try:
            _record_access(conn, rel_path, session_id, today)
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return


if __name__ == "__main__":
    main()
