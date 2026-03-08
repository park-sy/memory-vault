"""test_access_tracker.py — role-aware access_tracker tests."""

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult, make_temp_vault

import access_tracker


def _test_access_tracker(s: Suite) -> None:
    # Create temp vault for _is_tracked tests
    vault = make_temp_vault({
        "02-knowledge/patterns/test.md": "# test",
        "03-projects/myproj/overview.md": "# overview",
        "01-org/core/planner/memory.md": "# mem",
        "06-skills/pipeline.md": "# skill",
        "CLAUDE.md": "# claude",
        "01-org/core/planner/role.md": "# role",
        "01-org/head.md": "# head",
        "templates/note.md": "# template",
        "00-MOC/INDEX.md": "# moc",
        "02-knowledge/patterns/test.txt": "not md",
    })

    original_vault = access_tracker.VAULT_DIR
    access_tracker.VAULT_DIR = vault

    try:
        # 1-4. _is_tracked: tracked targets
        s.check("_is_tracked: 02-knowledge tracked", access_tracker._is_tracked(vault / "02-knowledge/patterns/test.md"))
        s.check("_is_tracked: 03-projects tracked", access_tracker._is_tracked(vault / "03-projects/myproj/overview.md"))
        s.check("_is_tracked: 01-org/core/memory.md tracked", access_tracker._is_tracked(vault / "01-org/core/planner/memory.md"))
        s.check("_is_tracked: 06-skills tracked", access_tracker._is_tracked(vault / "06-skills/pipeline.md"))

        # 5-10. _is_tracked: excluded
        s.check("_is_tracked: CLAUDE.md excluded", not access_tracker._is_tracked(vault / "CLAUDE.md"))
        s.check("_is_tracked: role.md excluded", not access_tracker._is_tracked(vault / "01-org/core/planner/role.md"))
        s.check("_is_tracked: head.md excluded", not access_tracker._is_tracked(vault / "01-org/head.md"))
        s.check("_is_tracked: templates/ excluded", not access_tracker._is_tracked(vault / "templates/note.md"))
        s.check("_is_tracked: 00-MOC/ excluded", not access_tracker._is_tracked(vault / "00-MOC/INDEX.md"))
        s.check("_is_tracked: non-.md excluded", not access_tracker._is_tracked(vault / "02-knowledge/patterns/test.txt"))

        # Outside vault
        s.check("_is_tracked: outside vault excluded", not access_tracker._is_tracked(Path("/tmp/other.md")))

    finally:
        access_tracker.VAULT_DIR = original_vault
        shutil.rmtree(vault, ignore_errors=True)

    # ── _infer_role tests ──

    s.check_eq("_infer_role: coder/memory.md → coder",
               access_tracker._infer_role("01-org/core/coder/memory.md"), "coder")
    s.check_eq("_infer_role: planner/memory.md → planner",
               access_tracker._infer_role("01-org/core/planner/memory.md"), "planner")
    s.check_eq("_infer_role: orchestrator/memory.md → orchestrator",
               access_tracker._infer_role("01-org/enabling/orchestrator/memory.md"), "orchestrator")
    s.check_none("_infer_role: non-memory.md → None",
                 access_tracker._infer_role("02-knowledge/patterns/test.md"))
    s.check_none("_infer_role: nested memory.md → None",
                 access_tracker._infer_role("01-org/core/coder/sub/memory.md"))

    # ── 도메인팀 역할 감지 ──
    s.check_eq("_infer_role: specialist-memory.md → learning-specialist",
               access_tracker._infer_role("03-projects/learning/specialist-memory.md"), "learning-specialist")
    s.check_eq("_infer_role: developer-memory.md → whos-life-developer",
               access_tracker._infer_role("03-projects/whos-life/developer-memory.md"), "whos-life-developer")
    s.check_none("_infer_role: context.md → None",
                 access_tracker._infer_role("03-projects/learning/context.md"))
    s.check_none("_infer_role: nested specialist-memory.md → None",
                 access_tracker._infer_role("03-projects/learning/sub/specialist-memory.md"))

    # ── DB 기능 테스트 ──

    tmp_dir = Path(tempfile.mkdtemp(prefix="access-tracker-test-"))
    db_path = tmp_dir / "test.db"

    try:
        # _init_db: 테이블 생성
        conn = access_tracker._init_db(db_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        s.check("init_db: file_role_access table created", "file_role_access" in table_names)
        s.check("init_db: session_role table created", "session_role" in table_names)
        s.check("init_db: old file_access removed", "file_access" not in table_names)

        # _record_access: memory.md 읽기 → 역할 설정 + 접근 기록
        session_id = "test-session-1"
        access_tracker._record_access(conn, "01-org/core/coder/memory.md", session_id, "2026-03-03")

        # session_role 확인
        row = conn.execute("SELECT active_role FROM session_role WHERE session_id = ?", (session_id,)).fetchone()
        s.check_eq("record_access: session_role set to coder", row[0], "coder")

        # file_role_access 확인
        row2 = conn.execute(
            "SELECT access_count FROM file_role_access WHERE file_path = ? AND role = ?",
            ("01-org/core/coder/memory.md", "coder"),
        ).fetchone()
        s.check_eq("record_access: memory.md count=1", row2[0], 1)

        # 이후 일반 파일 읽기 → 현재 역할(coder)로 기록
        access_tracker._record_access(conn, "02-knowledge/patterns/test.md", session_id, "2026-03-03")
        row3 = conn.execute(
            "SELECT access_count FROM file_role_access WHERE file_path = ? AND role = ?",
            ("02-knowledge/patterns/test.md", "coder"),
        ).fetchone()
        s.check_eq("record_access: file recorded as coder", row3[0], 1)

        # 역할 전환: planner memory.md 읽기
        access_tracker._record_access(conn, "01-org/core/planner/memory.md", session_id, "2026-03-03")
        row4 = conn.execute("SELECT active_role FROM session_role WHERE session_id = ?", (session_id,)).fetchone()
        s.check_eq("record_access: role switched to planner", row4[0], "planner")

        # 같은 파일을 planner로 다시 읽기
        access_tracker._record_access(conn, "02-knowledge/patterns/test.md", session_id, "2026-03-03")
        row5 = conn.execute(
            "SELECT access_count FROM file_role_access WHERE file_path = ? AND role = ?",
            ("02-knowledge/patterns/test.md", "planner"),
        ).fetchone()
        s.check_eq("record_access: file recorded as planner", row5[0], 1)

        # 역할 미설정 세션 → unknown
        session_id2 = "test-session-2"
        access_tracker._record_access(conn, "02-knowledge/patterns/test.md", session_id2, "2026-03-03")
        row6 = conn.execute(
            "SELECT access_count FROM file_role_access WHERE file_path = ? AND role = ?",
            ("02-knowledge/patterns/test.md", "unknown"),
        ).fetchone()
        s.check_eq("record_access: unknown role for new session", row6[0], 1)

        conn.close()

        # get_access_info: 역할 합산 조회
        last, count = access_tracker.get_access_info("02-knowledge/patterns/test.md", db_path)
        s.check_eq("get_access_info: last_accessed", last, "2026-03-03")
        s.check_eq("get_access_info: total count = coder(1) + planner(1) + unknown(1)", count, 3)

        # get_access_info: 존재하지 않는 파일
        last_none, count_none = access_tracker.get_access_info("nonexistent.md", db_path)
        s.check_none("get_access_info: nonexistent returns None", last_none)
        s.check_eq("get_access_info: nonexistent count=0", count_none, 0)

        # get_all_access_info: 전체 조회
        all_info = access_tracker.get_all_access_info(db_path)
        s.check("get_all_access_info: has test.md", "02-knowledge/patterns/test.md" in all_info)
        test_info = all_info["02-knowledge/patterns/test.md"]
        s.check_eq("get_all_access_info: total_count", test_info["total_count"], 3)
        s.check("get_all_access_info: has role_counts", "coder" in test_info["role_counts"])
        s.check_eq("get_all_access_info: coder count", test_info["role_counts"]["coder"], 1)

        # get_role_baselines
        baselines = access_tracker.get_role_baselines(db_path)
        s.check_eq("get_role_baselines: coder baseline", baselines.get("coder"), 1)
        s.check_eq("get_role_baselines: planner baseline", baselines.get("planner"), 1)

        # ── 도메인팀 역할 DB 테스트 ──
        conn2 = access_tracker._init_db(db_path)
        session_domain = "test-session-domain"

        # specialist-memory.md 읽기 → learning-specialist 역할 감지
        access_tracker._record_access(conn2, "03-projects/learning/specialist-memory.md", session_domain, "2026-03-06")
        row_domain = conn2.execute(
            "SELECT active_role FROM session_role WHERE session_id = ?", (session_domain,)
        ).fetchone()
        s.check_eq("domain: specialist-memory.md → learning-specialist role", row_domain[0], "learning-specialist")

        # 이후 일반 파일 읽기 → learning-specialist 역할로 기록
        access_tracker._record_access(conn2, "02-knowledge/patterns/test.md", session_domain, "2026-03-06")
        row_domain2 = conn2.execute(
            "SELECT access_count FROM file_role_access WHERE file_path = ? AND role = ?",
            ("02-knowledge/patterns/test.md", "learning-specialist"),
        ).fetchone()
        s.check_eq("domain: file recorded as learning-specialist", row_domain2[0], 1)

        conn2.close()

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("access-tracker", _test_access_tracker)
