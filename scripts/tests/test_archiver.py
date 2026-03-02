"""test_archiver.py — memory-archiver tests (~14 assertions)."""

import importlib
import shutil
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult, make_temp_vault


def _load_module(vault_dir: Path):
    """Load memory-archiver with patched VAULT_DIR."""
    mod = importlib.import_module("memory-archiver")
    original = mod.VAULT_DIR
    mod.VAULT_DIR = vault_dir
    mod.ARCHIVE_DIR = vault_dir / "archive"
    return mod, original


def _test_archiver(s: Suite) -> None:
    # ── _parse_frontmatter tests ──

    vault = make_temp_vault({
        "test_normal.md": '---\nimportance: 7\naccess_count: 3\nlast_accessed: "2026-01-15"\ntags: [a, b]\n---\n# Doc',
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

    # ── scan_vault / find_archive_candidates / generate_report ──

    vault2 = make_temp_vault({
        "02-knowledge/patterns/active.md": '---\nimportance: 8\naccess_count: 10\nlast_accessed: "2026-02-28"\ntags: [pattern]\n---\n# Active',
        "02-knowledge/patterns/cold.md": '---\nimportance: 2\naccess_count: 1\nlast_accessed: "2025-01-01"\ntags: [old]\n---\n# Cold',
        "02-knowledge/patterns/warm.md": '---\nimportance: 5\naccess_count: 3\nlast_accessed: "2026-02-01"\ntags: [warm]\n---\n# Warm',
        "CLAUDE.md": "# Should be excluded",
        "03-projects/test/no-fm.md": "# No frontmatter",
    })

    try:
        mod2, original2 = _load_module(vault2)
        mod2.SCAN_DIRS = ["02-knowledge", "03-projects"]

        # 9. scan_vault: returns tracked files with frontmatter
        files = mod2.scan_vault()
        s.check_eq("scan_vault: found 3 files with frontmatter", len(files), 3)

        # 10. scan_vault: excludes no-frontmatter
        paths = [f.path for f in files]
        s.check("scan_vault: no-fm excluded", "03-projects/test/no-fm.md" not in paths)

        # 11-12. find_archive_candidates
        candidates = mod2.find_archive_candidates(files, max_importance=3, max_access=2, min_cold_days=60)
        s.check_eq("find_candidates: cold file matches", len(candidates), 1)

        no_candidates = mod2.find_archive_candidates(files, max_importance=1, max_access=0, min_cold_days=9999)
        s.check_eq("find_candidates: strict filter = 0", len(no_candidates), 0)

        # 13-14. generate_report
        report = mod2.generate_report(files)
        s.check("report: has hot/warm/cold counts", "hot" in report and "warm" in report and "cold" in report)
        s.check("report: has avg_access_count", "avg_access_count" in report)

    finally:
        mod2.VAULT_DIR = original2
        shutil.rmtree(vault2, ignore_errors=True)


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("memory-archiver", _test_archiver)
