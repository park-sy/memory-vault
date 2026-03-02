"""test_frontmatter.py — frontmatter-tracker tests (~17 assertions)."""

import importlib
import shutil
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult, make_temp_vault


def _load_module(vault_dir: Path):
    """Load frontmatter-tracker with patched VAULT_DIR."""
    mod = importlib.import_module("frontmatter-tracker")
    # Monkeypatch VAULT_DIR
    original = mod.VAULT_DIR
    mod.VAULT_DIR = vault_dir
    return mod, original


def _test_frontmatter(s: Suite) -> None:
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

    try:
        mod, original_vault = _load_module(vault)

        # 1-4. _is_tracked: tracked targets
        s.check("_is_tracked: 02-knowledge tracked", mod._is_tracked(vault / "02-knowledge/patterns/test.md"))
        s.check("_is_tracked: 03-projects tracked", mod._is_tracked(vault / "03-projects/myproj/overview.md"))
        s.check("_is_tracked: 01-org/core/memory.md tracked", mod._is_tracked(vault / "01-org/core/planner/memory.md"))
        s.check("_is_tracked: 06-skills tracked", mod._is_tracked(vault / "06-skills/pipeline.md"))

        # 5-10. _is_tracked: excluded
        s.check("_is_tracked: CLAUDE.md excluded", not mod._is_tracked(vault / "CLAUDE.md"))
        s.check("_is_tracked: role.md excluded", not mod._is_tracked(vault / "01-org/core/planner/role.md"))
        s.check("_is_tracked: head.md excluded", not mod._is_tracked(vault / "01-org/head.md"))
        s.check("_is_tracked: templates/ excluded", not mod._is_tracked(vault / "templates/note.md"))
        s.check("_is_tracked: 00-MOC/ excluded", not mod._is_tracked(vault / "00-MOC/INDEX.md"))
        s.check("_is_tracked: non-.md excluded", not mod._is_tracked(vault / "02-knowledge/patterns/test.txt"))

        # Outside vault
        s.check("_is_tracked: outside vault excluded", not mod._is_tracked(Path("/tmp/other.md")))

        # 11-12. _has_frontmatter
        s.check("_has_frontmatter: with frontmatter", mod._has_frontmatter("---\ntype: test\n---\n# doc"))
        s.check("_has_frontmatter: without frontmatter", not mod._has_frontmatter("# just content"))

        # 13. _update_frontmatter: existing fields updated
        content_existing = '---\ntype: test\nlast_accessed: "2025-01-01"\naccess_count: 5\ntags: [a]\n---\n# Doc'
        result = mod._update_frontmatter(content_existing, "2026-03-01")
        s.check_contains("update_frontmatter: last_accessed updated", '2026-03-01', result)
        s.check_contains("update_frontmatter: access_count incremented", "access_count: 6", result)

        # 14-15. _update_frontmatter: missing fields added
        content_no_access = '---\ntype: test\n---\n# Doc'
        result2 = mod._update_frontmatter(content_no_access, "2026-03-01")
        s.check_contains("update_frontmatter: last_accessed added", "last_accessed:", result2)
        s.check_contains("update_frontmatter: access_count added", "access_count: 1", result2)

        # 16. _update_frontmatter: no frontmatter returns None
        result3 = mod._update_frontmatter("# no frontmatter", "2026-03-01")
        s.check_none("update_frontmatter: no frontmatter returns None", result3)

        # 17. _update_frontmatter: quoted values handled
        content_quoted = '---\ntype: test\nlast_accessed: "2025-06-15"\naccess_count: 3\n---\n# Doc'
        result4 = mod._update_frontmatter(content_quoted, "2026-03-01")
        s.check_contains("update_frontmatter: quoted date updated", "2026-03-01", result4)

    finally:
        mod.VAULT_DIR = original_vault
        shutil.rmtree(vault, ignore_errors=True)


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("frontmatter-tracker", _test_frontmatter)
