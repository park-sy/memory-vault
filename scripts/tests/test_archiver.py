"""test_archiver.py — memory-archiver tests (~14 assertions)."""

import importlib
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult, make_temp_vault
import access_tracker


def _load_module(vault_dir: Path):
    """Load memory-archiver with patched VAULT_DIR."""
    mod = importlib.import_module("memory-archiver")
    original = mod.VAULT_DIR
    mod.VAULT_DIR = vault_dir
    mod.ARCHIVE_DIR = vault_dir / "archive"
    return mod, original


def _setup_access_db(vault_dir: Path, records: list) -> Path:
    """Create a test access_tracker DB with file_role_access records.

    records: [(file_path, role, access_count, last_accessed), ...]
    """
    db_path = vault_dir / "storage" / "access_tracker.db"
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
    for fp, role, ac, la in records:
        conn.execute(
            "INSERT INTO file_role_access (file_path, role, access_count, last_accessed) VALUES (?, ?, ?, ?)",
            (fp, role, ac, la),
        )
    conn.commit()
    conn.close()
    return db_path


def _test_archiver(s: Suite) -> None:
    # ── _parse_frontmatter tests ──

    vault = make_temp_vault({
        "test_normal.md": '---\nimportance: 7\ntags: [a, b]\n---\n# Doc',
        "test_no_fm.md": "# Just content\nNo frontmatter here.",
        "test_incomplete.md": "---\nimportance: 5\n# Missing closing ---",
    })

    try:
        mod, original = _load_module(vault)

        # 1. _parse_frontmatter: normal
        fm = mod._parse_frontmatter(vault / "test_normal.md")
        s.check("parse_frontmatter: normal returns dict", fm is not None and isinstance(fm, dict))
        s.check_eq("parse_frontmatter: importance=7", fm.get("importance"), "7")

        # 2. _parse_frontmatter: no frontmatter
        fm2 = mod._parse_frontmatter(vault / "test_no_fm.md")
        s.check_none("parse_frontmatter: no frontmatter returns None", fm2)

        # 3. _parse_frontmatter: incomplete
        fm3 = mod._parse_frontmatter(vault / "test_incomplete.md")
        s.check_none("parse_frontmatter: incomplete returns None", fm3)

        # ── _days_since tests ──

        # 4. _days_since: valid date
        days = mod._days_since("2020-01-01")
        s.check_gt("days_since: valid date returns positive int", days, 0)

        # 5. _days_since: invalid date
        days_bad = mod._days_since("not-a-date")
        s.check_eq("days_since: invalid date returns 9999", days_bad, 9999)

        # ── _parse_tags tests ──

        # 6. _parse_tags: [a, b, c]
        tags1 = mod._parse_tags("[a, b, c]")
        s.check_eq("parse_tags: [a,b,c]", tags1, ["a", "b", "c"])

        # 7. _parse_tags: plain
        tags2 = mod._parse_tags("single")
        s.check_eq("parse_tags: plain", tags2, ["single"])

        # 8. _parse_tags: empty
        tags3 = mod._parse_tags("")
        s.check_eq("parse_tags: empty", tags3, [])

    finally:
        mod.VAULT_DIR = original
        shutil.rmtree(vault, ignore_errors=True)

    # ── scan_vault / find_archive_candidates / generate_report (DB 기반) ──

    vault2 = make_temp_vault({
        "02-knowledge/patterns/active.md": '---\nimportance: 8\ntags: [pattern]\n---\n# Active',
        "02-knowledge/patterns/cold.md": '---\nimportance: 2\ntags: [old]\n---\n# Cold',
        "02-knowledge/patterns/warm.md": '---\nimportance: 5\ntags: [warm]\n---\n# Warm',
        "CLAUDE.md": "# Should be excluded",
        "03-projects/test/no-fm.md": "# No frontmatter",
    })

    # role-aware DB records: (file_path, role, access_count, last_accessed)
    # coder memory.md baseline = 100
    db_path = _setup_access_db(vault2, [
        # coder baseline: memory.md 100회
        ("01-org/core/coder/memory.md", "coder", 100, "2026-03-03"),
        # active.md: coder 50회 → rate 50% (hot)
        ("02-knowledge/patterns/active.md", "coder", 50, "2026-02-28"),
        # cold.md: coder 1회 → rate 1% (cold)
        ("02-knowledge/patterns/cold.md", "coder", 1, "2025-01-01"),
        # warm.md: coder 5회 → rate 5%
        ("02-knowledge/patterns/warm.md", "coder", 5, "2026-02-01"),
    ])

    try:
        mod2, original2 = _load_module(vault2)
        mod2.SCAN_DIRS = ["02-knowledge", "03-projects"]

        # 9. scan_vault: returns tracked files with frontmatter
        files = mod2.scan_vault(db_path=db_path)
        s.check_eq("scan_vault: found 3 files with frontmatter", len(files), 3)

        # 10. scan_vault: excludes no-frontmatter
        paths = [f.path for f in files]
        s.check("scan_vault: no-fm excluded", "03-projects/test/no-fm.md" not in paths)

        # 11. MemoryFile has role-aware fields
        active_file = next(f for f in files if "active" in f.path)
        s.check_gt("scan_vault: active file max_reference_rate > 0", active_file.max_reference_rate, 0)
        s.check("scan_vault: active file has role_counts", "coder" in active_file.role_counts)

        # 12-13. find_archive_candidates (rate 기반)
        candidates = mod2.find_archive_candidates(files, max_importance=3, max_rate=0.05, min_cold_days=60)
        s.check_eq("find_candidates: cold file with low rate matches", len(candidates), 1)

        no_candidates = mod2.find_archive_candidates(files, max_importance=1, max_rate=0.0, min_cold_days=9999)
        s.check_eq("find_candidates: strict filter = 0", len(no_candidates), 0)

        # 14-15. generate_report
        report = mod2.generate_report(files)
        s.check("report: has hot/warm/cold counts", "hot" in report and "warm" in report and "cold" in report)
        s.check("report: has avg_access_count", "avg_access_count" in report)

    finally:
        mod2.VAULT_DIR = original2
        shutil.rmtree(vault2, ignore_errors=True)


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("memory-archiver", _test_archiver)
