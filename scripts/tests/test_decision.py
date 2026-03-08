"""test_decision.py — decision-clone.py tests (~16 assertions)."""

import importlib
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult, make_temp_vault

# Import the module (hyphenated filename)
dc = importlib.import_module("decision-clone")
Decision = dc.Decision


def _test_decision(s: Suite) -> None:
    # ── Decision dataclass tests ──

    # 1. immutability (frozen)
    d = Decision(
        id="D-001", category="architecture", date="2026-03-01",
        context="test context", options="A, B", chosen="A",
        rationale="because A is better",
    )
    s.check_raises("Decision: frozen (immutable)", AttributeError,
                   lambda: setattr(d, "chosen", "B"))

    # 2. with_update returns new object
    d2 = d.with_update(chosen="B", outcome="correct")
    s.check_eq("with_update: chosen changed", d2.chosen, "B")
    s.check_eq("with_update: outcome changed", d2.outcome, "correct")
    s.check_eq("with_update: original unchanged", d.chosen, "A")

    # 3. to_markdown format
    md = d.to_markdown()
    s.check_contains("to_markdown: has ### D-001", "### D-001", md)
    s.check_contains("to_markdown: has **context**:", "**context**:", md)
    s.check_contains("to_markdown: has **chosen**:", "**chosen**:", md)

    # ── next_id tests ──

    # 4. empty list → D-001
    s.check_eq("next_id: empty = D-001", dc.next_id([]), "D-001")

    # 5. existing decisions → next sequential
    decisions = [
        Decision("D-003", "a", "d", "c", "o", "ch", "r"),
        Decision("D-005", "a", "d", "c", "o", "ch", "r"),
    ]
    s.check_eq("next_id: after D-005 = D-006", dc.next_id(decisions), "D-006")

    # ── parse_decisions / write_decisions roundtrip ──

    tmp_dir = Path(tempfile.mkdtemp(prefix="decision-test-"))
    try:
        log_path = tmp_dir / "test-log.md"

        # 6. parse empty/nonexistent → empty list
        s.check_eq("parse_decisions: nonexistent = []", dc.parse_decisions(log_path), [])

        # 7-8. write then parse roundtrip
        test_decisions = [
            Decision("D-001", "architecture", "2026-03-01", "ctx1", "A,B", "A", "reason1"),
            Decision("D-002", "workflow", "2026-03-01", "ctx2", "X,Y", "Y", "reason2",
                     confidence="high", outcome="correct", tags="test"),
        ]
        dc.write_decisions(log_path, test_decisions, "2026-03-01")
        parsed = dc.parse_decisions(log_path)
        s.check_eq("write+parse roundtrip: count", len(parsed), 2)
        s.check_eq("write+parse roundtrip: D-001 chosen", parsed[0].chosen, "A")

        # 9. written file has frontmatter
        content = log_path.read_text()
        s.check_contains("write_decisions: has frontmatter", "---", content)
        s.check_contains("write_decisions: has total_entries", "total_entries: 2", content)

        # 10. parse with empty file
        empty_path = tmp_dir / "empty.md"
        empty_path.write_text("")
        s.check_eq("parse_decisions: empty file = []", dc.parse_decisions(empty_path), [])

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── seed tests ──
    tmp_dir2 = Path(tempfile.mkdtemp(prefix="seed-test-"))
    try:
        # Monkeypatch DECISION_LOG
        original_log = dc.DECISION_LOG
        original_clone_dir = dc.CLONE_DIR
        dc.CLONE_DIR = tmp_dir2
        dc.DECISION_LOG = tmp_dir2 / "decision-log.md"

        # 11. seed creates entries
        seeds = dc._build_seeds()
        s.check_eq("seed: 16 pre-extracted decisions", len(seeds), 16)

        # 12. seed numbering is sequential
        numbered = []
        for seed in seeds:
            sid = dc.next_id(numbered)
            numbered.append(seed.with_update(id=sid))
        s.check_eq("seed: first = D-001", numbered[0].id, "D-001")
        s.check_eq("seed: last = D-016", numbered[-1].id, "D-016")

        # 13. seed entries are non-empty
        for d in numbered:
            if not d.context:
                s.check(f"seed: {d.id} has context", False)
                break
        else:
            s.check("seed: all entries have context", True)

        dc.DECISION_LOG = original_log
        dc.CLONE_DIR = original_clone_dir
    finally:
        shutil.rmtree(tmp_dir2, ignore_errors=True)

    # ── accuracy calculation logic ──

    # 14. correct=1.0, wrong=0.0, partial=0.5
    scored = [
        Decision("D-001", "a", "d", "c", "o", "ch", "r", outcome="correct"),
        Decision("D-002", "a", "d", "c", "o", "ch", "r", outcome="wrong"),
        Decision("D-003", "a", "d", "c", "o", "ch", "r", outcome="partial"),
    ]
    total_score = sum(
        1.0 if d.outcome == "correct" else 0.5 if d.outcome == "partial" else 0.0
        for d in scored
    )
    accuracy = total_score / len(scored)
    s.check_eq("accuracy: correct+wrong+partial = 0.5", accuracy, 0.5)

    # 15. all correct = 1.0
    all_correct = [
        Decision("D-001", "a", "d", "c", "o", "ch", "r", outcome="correct"),
        Decision("D-002", "a", "d", "c", "o", "ch", "r", outcome="correct"),
    ]
    acc2 = sum(1.0 if d.outcome == "correct" else 0.0 for d in all_correct) / len(all_correct)
    s.check_eq("accuracy: all correct = 1.0", acc2, 1.0)

    # 16. category validity
    s.check("categories: architecture valid", "architecture" in dc.CATEGORIES)
    s.check("categories: workflow valid", "workflow" in dc.CATEGORIES)
    s.check("categories: unknown invalid", "unknown" not in dc.CATEGORIES)

    # ── _is_decision tests ──

    # 17. exploratory tag → not a decision
    d_exp = Decision("D-099", "uncategorized", "2026-03-07", "ctx", "A,B", "뭐야?",
                     "뭐야?", tags="auto-captured, exploratory")
    s.check("_is_decision: exploratory = False", not dc._is_decision(d_exp))

    # 18. normal tag → is a decision
    d_normal = Decision("D-100", "architecture", "2026-03-07", "ctx", "A,B", "A",
                        "reason", tags="auto-captured")
    s.check("_is_decision: normal = True", dc._is_decision(d_normal))

    # ── tag command roundtrip ──

    tmp_tag = Path(tempfile.mkdtemp(prefix="tag-test-"))
    try:
        tag_log = tmp_tag / "decision-log.md"
        test_d = [
            Decision("D-001", "architecture", "2026-03-07", "ctx", "A,B", "A",
                     "reason", tags="auto-captured"),
        ]
        dc.write_decisions(tag_log, test_d, "2026-03-07")

        # Monkeypatch
        orig_log = dc.DECISION_LOG
        dc.DECISION_LOG = tag_log

        # 19. tag adds correctly
        class FakeArgs:
            id = "D-001"
            tag = "exploratory"
        dc.cmd_tag(FakeArgs())
        parsed_tag = dc.parse_decisions(tag_log)
        s.check_contains("tag: exploratory added", "exploratory", parsed_tag[0].tags)

        # 20. tag deduplication
        dc.cmd_tag(FakeArgs())  # add same tag again
        parsed_tag2 = dc.parse_decisions(tag_log)
        tag_count = parsed_tag2[0].tags.count("exploratory")
        s.check_eq("tag: no duplicate", tag_count, 1)

        dc.DECISION_LOG = orig_log
    finally:
        shutil.rmtree(tmp_tag, ignore_errors=True)


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("decision-clone", _test_decision)
