"""Minimal test harness — stdlib only, no pytest dependency.

Provides Suite for assertions, TestResult for reporting,
and helpers for temp vault creation and JSONL output.
"""

import json
import os
import shutil
import tempfile
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Type


@dataclass(frozen=True)
class TestResult:
    suite: str
    label: str
    result: str  # "PASS" | "FAIL"
    detail: str = ""


class Suite:
    """Collects test assertions within a named suite."""

    def __init__(self, name: str):
        self.name = name
        self._results: List[TestResult] = []

    @property
    def results(self) -> List[TestResult]:
        return list(self._results)

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        result = "PASS" if condition else "FAIL"
        if not condition and not detail:
            detail = "condition was False"
        self._results.append(TestResult(suite=self.name, label=label, result=result, detail=detail))

    def check_eq(self, label: str, expected, actual) -> None:
        ok = expected == actual
        detail = "" if ok else f"expected {expected!r}, got {actual!r}"
        self._results.append(TestResult(suite=self.name, label=label, result="PASS" if ok else "FAIL", detail=detail))

    def check_raises(self, label: str, exc_type: Type[BaseException], fn: Callable) -> None:
        try:
            fn()
            self._results.append(TestResult(
                suite=self.name, label=label, result="FAIL",
                detail=f"expected {exc_type.__name__}, no exception raised",
            ))
        except exc_type:
            self._results.append(TestResult(suite=self.name, label=label, result="PASS"))
        except Exception as e:
            self._results.append(TestResult(
                suite=self.name, label=label, result="FAIL",
                detail=f"expected {exc_type.__name__}, got {type(e).__name__}: {e}",
            ))

    def check_contains(self, label: str, needle: str, haystack: str) -> None:
        ok = needle in haystack
        detail = "" if ok else f"{needle!r} not found in {haystack[:200]!r}"
        self._results.append(TestResult(suite=self.name, label=label, result="PASS" if ok else "FAIL", detail=detail))

    def check_not_contains(self, label: str, needle: str, haystack: str) -> None:
        ok = needle not in haystack
        detail = "" if ok else f"{needle!r} unexpectedly found in output"
        self._results.append(TestResult(suite=self.name, label=label, result="PASS" if ok else "FAIL", detail=detail))

    def check_is_instance(self, label: str, obj, expected_type: type) -> None:
        ok = isinstance(obj, expected_type)
        detail = "" if ok else f"expected {expected_type.__name__}, got {type(obj).__name__}"
        self._results.append(TestResult(suite=self.name, label=label, result="PASS" if ok else "FAIL", detail=detail))

    def check_gt(self, label: str, a, b) -> None:
        ok = a > b
        detail = "" if ok else f"{a!r} is not > {b!r}"
        self._results.append(TestResult(suite=self.name, label=label, result="PASS" if ok else "FAIL", detail=detail))

    def check_none(self, label: str, value) -> None:
        ok = value is None
        detail = "" if ok else f"expected None, got {value!r}"
        self._results.append(TestResult(suite=self.name, label=label, result="PASS" if ok else "FAIL", detail=detail))

    def check_not_none(self, label: str, value) -> None:
        ok = value is not None
        detail = "" if ok else "expected non-None value"
        self._results.append(TestResult(suite=self.name, label=label, result="PASS" if ok else "FAIL", detail=detail))


def run_suite(name: str, test_fn: Callable[[Suite], None]) -> List[TestResult]:
    """Run a test function, catching unexpected exceptions."""
    suite = Suite(name)
    try:
        test_fn(suite)
    except Exception as e:
        tb = traceback.format_exc()
        suite._results.append(TestResult(
            suite=name,
            label="[CRASH] unhandled exception",
            result="FAIL",
            detail=f"{type(e).__name__}: {e}\n{tb}",
        ))
    return suite.results


def write_jsonl(results: List[TestResult], path: Path) -> None:
    """Write results as JSONL for test-report-gen.py consumption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def make_temp_vault(structure: Dict[str, str]) -> Path:
    """Create a temporary vault directory with given file structure.

    structure: {"relative/path.md": "file content", ...}
    Returns the temp vault root Path. Caller should clean up with shutil.rmtree.
    """
    root = Path(tempfile.mkdtemp(prefix="vault-test-"))
    for rel_path, content in structure.items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return root


class EnvBackup:
    """Context manager to backup/restore environment variables."""

    def __init__(self, keys: List[str]):
        self._keys = keys
        self._backup: Dict[str, Optional[str]] = {}

    def __enter__(self):
        for key in self._keys:
            self._backup[key] = os.environ.get(key)
        return self

    def __exit__(self, *args):
        for key, value in self._backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
