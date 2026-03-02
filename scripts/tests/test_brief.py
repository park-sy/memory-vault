"""test_brief.py — domain-context-brief tests (~13 assertions)."""

import importlib
import shutil
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult, make_temp_vault


def _load_module(vault_dir: Path):
    """Load domain-context-brief with patched paths."""
    mod = importlib.import_module("domain-context-brief")
    original_vault = mod.VAULT_DIR
    original_projects = mod.PROJECTS_DIR
    mod.VAULT_DIR = vault_dir
    mod.PROJECTS_DIR = vault_dir / "03-projects"
    return mod, (original_vault, original_projects)


def _test_brief(s: Suite) -> None:
    mod = importlib.import_module("domain-context-brief")
    originals = (mod.VAULT_DIR, mod.PROJECTS_DIR)

    # ── _content_hash tests ──

    # 1. deterministic
    h1 = mod._content_hash("hello world")
    h2 = mod._content_hash("hello world")
    s.check_eq("content_hash: deterministic", h1, h2)

    # 2. different input → different hash
    h3 = mod._content_hash("different content")
    s.check("content_hash: different input", h1 != h3)

    # ── _extract_sections tests ──

    # 3. extracts H2 sections
    md = "# Title\n\n## Section A\nContent A\n\n## Section B\nContent B\n"
    sections = mod._extract_sections(md)
    s.check_eq("extract_sections: found 2 sections", len(sections), 2)
    s.check_contains("extract_sections: Section A content", "Content A", sections.get("Section A", ""))

    # 4. no sections
    sections2 = mod._extract_sections("# Title only\nNo H2 here")
    s.check_eq("extract_sections: no H2 = empty dict", len(sections2), 0)

    # ── _compress_table tests ──

    # 5. under limit → unchanged
    small_table = "| H1 | H2 |\n|---|---|\n| a | b |\n| c | d |"
    compressed = mod._compress_table(small_table, max_rows=10)
    s.check_eq("compress_table: under limit unchanged", compressed.strip(), small_table.strip())

    # 6. over limit → truncated
    rows = ["| H1 | H2 |", "|---|---|"] + [f"| r{i} | v{i} |" for i in range(20)]
    big_table = "\n".join(rows)
    compressed2 = mod._compress_table(big_table, max_rows=5)
    s.check_contains("compress_table: over limit has truncation", "+", compressed2)

    # ── generate_brief tests ──

    vault = make_temp_vault({
        "03-projects/testproj/context.md": (
            "---\ntype: context\n---\n"
            "# TestProj\n\n"
            "## 프로젝트 요약\nThis is a test project.\n\n"
            "## 스택\nPython, SQLite\n\n"
            "## 비관련 섹션\nShould be excluded.\n"
        ),
        "03-projects/nocontext/overview.md": "# No context.md here\n",
    })

    try:
        mod.VAULT_DIR = vault
        mod.PROJECTS_DIR = vault / "03-projects"

        # 7-8. generate_brief: priority sections only
        brief = mod.generate_brief("testproj")
        s.check_contains("generate_brief: includes priority section", "프로젝트 요약", brief)
        s.check_not_contains("generate_brief: excludes non-priority", "비관련 섹션", brief)

        # 9. generate_brief: context.md missing
        brief_missing = mod.generate_brief("nonexistent")
        s.check_contains("generate_brief: missing context.md error", "context.md", brief_missing)

        # 10. generate_brief: frontmatter removed
        s.check_not_contains("generate_brief: no frontmatter in output", "type: context", brief)

        # 11. generate_brief: MAX_LINES respected
        # Create a project with very long context.md
        long_content = "---\ntype: context\n---\n# Long\n\n"
        for section in mod.PRIORITY_SECTIONS:
            long_content += f"## {section}\n" + ("Line of content\n" * 20) + "\n"
        (vault / "03-projects" / "longproj").mkdir(parents=True, exist_ok=True)
        (vault / "03-projects" / "longproj" / "context.md").write_text(long_content)

        original_max = mod.MAX_LINES
        mod.MAX_LINES = 10  # force truncation
        brief_long = mod.generate_brief("longproj")
        s.check_contains("generate_brief: MAX_LINES truncation", "truncated", brief_long)
        mod.MAX_LINES = original_max

        # 12. get_brief: caching
        brief1 = mod.get_brief("testproj")
        brief2 = mod.get_brief("testproj")  # should use cache
        s.check_eq("get_brief: cache hit returns same", brief1, brief2)

        # 13. list_projects: only projects with context.md
        projects = mod.list_projects()
        names = [p["name"] for p in projects]
        s.check("list_projects: testproj included", "testproj" in names)
        s.check("list_projects: nocontext excluded", "nocontext" not in names)

    finally:
        mod.VAULT_DIR = originals[0]
        mod.PROJECTS_DIR = originals[1]
        shutil.rmtree(vault, ignore_errors=True)


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("domain-context-brief", _test_brief)
