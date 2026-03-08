#!/usr/bin/env python3
"""test-vault.py — Memory Vault test runner.

Usage:
    python3 scripts/test-vault.py                    # run all + HTML report
    python3 scripts/test-vault.py --suite msgbus      # single suite
    python3 scripts/test-vault.py --no-report         # skip HTML
    python3 scripts/test-vault.py --verbose           # real-time output
"""

import argparse
import importlib
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
TESTS_DIR = SCRIPTS_DIR / "tests"
STORAGE_DIR = SCRIPTS_DIR.parent / "storage"
JSONL_PATH = Path("/tmp/cc-vault-test-results.jsonl")
REPORT_SCRIPT = SCRIPTS_DIR / "test-report-gen.py"

# Ensure scripts dir is on path for imports
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(TESTS_DIR))

# Suite registry: name -> module name
SUITES = [
    ("msgbus", "test_msgbus"),
    ("access-tracker", "test_access_tracker"),
    ("archiver", "test_archiver"),
    ("brief", "test_brief"),
    ("inbox-deliver", "test_inbox_deliver"),
    ("notify", "test_notify"),
    ("check-inbox", "test_check_inbox"),
    ("decision", "test_decision"),
    ("capture-hook", "test_capture_hook"),
    ("telegram-api", "test_telegram_api"),
]


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def main():
    parser = argparse.ArgumentParser(description="Memory Vault Test Runner")
    parser.add_argument("--suite", default=None, help="Run single suite by name")
    parser.add_argument("--no-report", action="store_true", help="Skip HTML report")
    parser.add_argument("--verbose", action="store_true", help="Print results in real time")
    args = parser.parse_args()

    suites_to_run = SUITES
    if args.suite:
        suites_to_run = [(n, m) for n, m in SUITES if n == args.suite]
        if not suites_to_run:
            print(f"Unknown suite: {args.suite}")
            print(f"Available: {', '.join(n for n, _ in SUITES)}")
            sys.exit(1)

    all_results = []
    start = time.time()

    for suite_name, module_name in suites_to_run:
        try:
            mod = importlib.import_module(module_name)
            results = mod.run(verbose=args.verbose)
            all_results.extend(results)

            passed = sum(1 for r in results if r.result == "PASS")
            failed = sum(1 for r in results if r.result != "PASS")
            total = len(results)

            if failed > 0:
                status = _color(f"FAIL ({failed}/{total})", "31")
            else:
                status = _color(f"PASS ({passed}/{total})", "32")

            print(f"  {suite_name:<20s} {status}")

            if args.verbose:
                for r in results:
                    icon = _color("PASS", "32") if r.result == "PASS" else _color("FAIL", "31")
                    line = f"    {icon}  {r.label}"
                    if r.detail:
                        line += f"  -- {r.detail}"
                    print(line)

        except Exception as e:
            print(f"  {suite_name:<20s} {_color('ERROR', '31')}  {e}")
            from tests.harness import TestResult
            all_results.append(TestResult(
                suite=suite_name,
                label="[IMPORT ERROR]",
                result="FAIL",
                detail=str(e),
            ))

    elapsed = int(time.time() - start)
    total = len(all_results)
    passed = sum(1 for r in all_results if r.result == "PASS")
    failed = total - passed

    print()
    print(f"{'=' * 50}")
    if failed == 0:
        print(_color(f"  ALL PASSED: {passed}/{total} ({elapsed}s)", "32"))
    else:
        print(_color(f"  {failed} FAILED / {total} total ({elapsed}s)", "31"))
    print(f"{'=' * 50}")

    # Write JSONL
    from tests.harness import write_jsonl
    write_jsonl(all_results, JSONL_PATH)

    # Generate HTML report
    if not args.no_report and REPORT_SCRIPT.exists():
        report_path = STORAGE_DIR / "test-report.html"
        subprocess.run(
            [
                sys.executable, str(REPORT_SCRIPT),
                "--input", str(JSONL_PATH),
                "--output", str(report_path),
                "--elapsed", str(elapsed),
                "--total", str(total),
                "--pass", str(passed),
                "--fail", str(failed),
            ],
            capture_output=True,
            timeout=10,
        )
        print(f"\n  Report: {report_path}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
