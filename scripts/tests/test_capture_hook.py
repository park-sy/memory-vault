"""test_capture_hook.py — capture-decision-hook tests (~8 assertions)."""

import importlib
import json
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult

# Import hyphenated module
hook = importlib.import_module("capture-decision-hook")


def _test_capture_hook(s: Suite) -> None:
    # ── _extract_answers tests ──

    # 1. answers from tool_response dict
    payload1 = {
        "tool_response": {
            "answers": {"Which approach?": "Option A"},
        },
    }
    answers1 = hook._extract_answers(payload1)
    s.check_eq("extract_answers: from tool_response dict", answers1, {"Which approach?": "Option A"})

    # 2. answers from tool_response string (JSON)
    payload2 = {
        "tool_response": json.dumps({"answers": {"Q?": "A"}}),
    }
    answers2 = hook._extract_answers(payload2)
    s.check_eq("extract_answers: from JSON string response", answers2, {"Q?": "A"})

    # 3. answers from tool_input.answers
    payload3 = {
        "tool_response": {},
        "tool_input": {
            "answers": {"Input Q?": "Input A"},
        },
    }
    answers3 = hook._extract_answers(payload3)
    s.check_eq("extract_answers: from tool_input", answers3, {"Input Q?": "Input A"})

    # 4. no answers found → empty dict
    payload4 = {
        "tool_response": "not json at all {{{",
        "tool_input": {},
    }
    answers4 = hook._extract_answers(payload4)
    s.check_eq("extract_answers: no answers = {}", answers4, {})

    # ── _extract_annotations tests ──

    # 5. annotations from tool_response
    payload5 = {
        "tool_response": {
            "annotations": {"Q?": {"notes": "user note"}},
        },
    }
    ann5 = hook._extract_annotations(payload5)
    s.check_eq("extract_annotations: from tool_response", ann5, {"Q?": {"notes": "user note"}})

    # 6. annotations from tool_input
    payload6 = {
        "tool_response": {},
        "tool_input": {
            "annotations": {"Q?": {"notes": "from input"}},
        },
    }
    ann6 = hook._extract_annotations(payload6)
    s.check_eq("extract_annotations: from tool_input", ann6, {"Q?": {"notes": "from input"}})

    # 7. no annotations → empty dict
    payload7 = {"tool_response": {}, "tool_input": {}}
    ann7 = hook._extract_annotations(payload7)
    s.check_eq("extract_annotations: none = {}", ann7, {})

    # 8. annotations with nested notes extraction
    annotations = {"Which DB?": {"notes": "PostgreSQL is safer"}}
    q_ann = annotations.get("Which DB?", {})
    note = q_ann.get("notes", "") if isinstance(q_ann, dict) else ""
    s.check_eq("annotation notes extraction", note, "PostgreSQL is safer")


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("capture-decision-hook", _test_capture_hook)
